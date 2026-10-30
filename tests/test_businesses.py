import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.models import Business, User


def test_user_without_business_is_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match='"business_id" .* violates not-null'):
        with db_session.begin_nested():
            db_session.add(
                User(
                    email="nobody@example.com",
                    hashed_password="not-a-real-hash",
                )
            )


def test_business_with_users_cannot_be_deleted(db_session: Session) -> None:
    business = Business(name="Acme", slug="acme")
    db_session.add(business)
    db_session.flush()

    db_session.add(
        User(
            email="owner@acme.example",
            hashed_password="not-a-real-hash",
            business_id=business.id,
        )
    )
    db_session.flush()

    # A savepoint lets the expected failure roll back without ending the test's outer transaction.
    # Matching the name proves the RESTRICT foreign key refused, not another rule.
    with pytest.raises(IntegrityError, match="fk_users_business_id_businesses"):
        with db_session.begin_nested():
            db_session.delete(business)


def test_database_rejects_duplicate_slug(db_session: Session) -> None:
    db_session.add(Business(name="Acme", slug="acme"))
    db_session.flush()

    with pytest.raises(IntegrityError, match="uq_businesses_slug"):
        with db_session.begin_nested():
            db_session.add(Business(name="Acme Copy", slug="acme"))


@pytest.mark.parametrize(
    "slug",
    [
        "כהן",
        "Cohen",
        "cohen plumbing",
        "-cohen",
        "cohen-",
        "cohen--plumbing",
        "",
    ],
)
def test_invalid_slug_is_rejected(db_session: Session, slug: str) -> None:
    with pytest.raises(IntegrityError, match="ck_businesses_slug_format"):
        with db_session.begin_nested():
            db_session.add(Business(name="Cohen", slug=slug))


def test_hebrew_business_name_round_trip(db_session: Session) -> None:
    hebrew_name = 'אינסטלציה כהן בע"מ'

    business = Business(name=hebrew_name, slug="cohen-plumbing")
    db_session.add(business)
    db_session.flush()

    stored_name = db_session.execute(
        text("SELECT name FROM businesses WHERE id = :id"),
        {"id": business.id},
    ).scalar_one()

    assert stored_name == hebrew_name


def test_database_encoding_is_utf8(db_session: Session) -> None:
    encoding = db_session.execute(text("SHOW server_encoding")).scalar_one()

    assert encoding == "UTF8"
