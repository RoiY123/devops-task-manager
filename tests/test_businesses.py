import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.models import Business, User


def test_registered_user_joins_legacy_business(
    client: TestClient,
    db_session: Session,
) -> None:
    response = client.post(
        "/register",
        json={
            "email": "alice@example.com",
            "password": "password123",
        },
    )

    assert response.status_code == 201

    user = db_session.scalar(
        select(User).where(User.email == "alice@example.com")
    )

    assert user is not None
    assert user.business.slug == "legacy"


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
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.delete(business)


def test_duplicate_slug_is_rejected(db_session: Session) -> None:
    db_session.add(Business(name="Acme", slug="acme"))
    db_session.flush()

    with pytest.raises(IntegrityError):
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
    with pytest.raises(IntegrityError):
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
