import unicodedata

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend import businesses
from app.backend.accounts import OperatorError
from app.backend.businesses import delete_business, rename_business
from app.backend.models import Business


def business_by_slug(db: Session, slug: str) -> Business | None:
    return db.scalar(select(Business).where(Business.slug == slug))


@pytest.fixture
def empty_business(db_session: Session) -> Business:
    business = Business(name="עסק ריק", slug="empty-business")
    db_session.add(business)
    db_session.flush()
    return business


def test_rename_changes_only_the_display_name(
    db_session: Session,
    test_business: Business,
    user_factory,
) -> None:
    user = user_factory("avi@example.com")
    business_id = test_business.id

    # Kaf, dagesh, holam: the non-standard mark order.
    # Escapes keep editors from normalizing the literal,
    # which would make the test prove nothing.
    typed_name = "  \u05db\u05bc\u05b9\u05d4\u05df  "
    assert unicodedata.normalize("NFC", typed_name) != typed_name

    previous = rename_business(db_session, slug="test-business", name=typed_name)

    renamed = business_by_slug(db_session, "test-business")
    assert previous == "עסק בדיקות"
    assert renamed.id == business_id
    assert renamed.name == "\u05db\u05b9\u05bc\u05d4\u05df"
    assert user.business_id == business_id


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("   ", "must not be empty"),
        ("א" * 201, "at most 200 characters"),
    ],
)
def test_rename_rejects_invalid_names(
    db_session: Session,
    test_business: Business,
    name: str,
    message: str,
) -> None:
    with pytest.raises(OperatorError, match=message):
        rename_business(db_session, slug="test-business", name=name)

    assert business_by_slug(db_session, "test-business").name == "עסק בדיקות"


# What the left arrow key inserts at the CLI's prompts: ESC [ D.
ARROW_LEFT = chr(27) + "[D"
RIGHT_TO_LEFT_MARK = chr(0x200F)


def test_rename_rejects_arrow_key_sequences(
    db_session: Session,
    test_business: Business,
) -> None:
    with pytest.raises(OperatorError, match="control characters"):
        rename_business(db_session, slug="test-business", name=f"שם{ARROW_LEFT}חדש")

    assert business_by_slug(db_session, "test-business").name == "עסק בדיקות"


def test_rename_keeps_direction_marks(
    db_session: Session,
    test_business: Business,
) -> None:
    # Invisible like a control character, but a legitimate part of Hebrew text.
    name = f"שם {RIGHT_TO_LEFT_MARK}2026"

    rename_business(db_session, slug="test-business", name=name)

    assert business_by_slug(db_session, "test-business").name == name


def test_rename_rejects_unknown_business(db_session: Session) -> None:
    with pytest.raises(OperatorError, match="No business with slug 'no-such'"):
        rename_business(db_session, slug="no-such", name="שם")


def test_delete_removes_an_empty_business(
    db_session: Session,
    empty_business: Business,
) -> None:
    delete_business(db_session, slug="empty-business")

    assert business_by_slug(db_session, "empty-business") is None


def test_delete_refuses_a_business_with_users(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")

    with pytest.raises(OperatorError, match="has 1 users; remove them first"):
        delete_business(db_session, slug="test-business")

    assert business_by_slug(db_session, "test-business") is not None


def test_database_refuses_if_users_appear_after_the_check(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")
    # The failed delete rolls back; committed setup survives it.
    db_session.commit()

    # Simulates a user added between the app's check and the delete:
    # only the RESTRICT foreign key is left to refuse.
    monkeypatch.setattr(
        businesses, "ensure_business_is_empty", lambda db, business: None
    )

    with pytest.raises(OperatorError, match="nothing was deleted"):
        delete_business(db_session, slug="test-business")

    assert business_by_slug(db_session, "test-business") is not None


def test_delete_rejects_unknown_business(db_session: Session) -> None:
    with pytest.raises(OperatorError, match="No business with slug 'no-such'"):
        delete_business(db_session, slug="no-such")
