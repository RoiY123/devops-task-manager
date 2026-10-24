import unicodedata

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.models import ROLE_ADMIN, ROLE_MEMBER, Business, User
from app.backend.onboarding import OnboardingError, create_business_with_admin


VALID = {
    "name": "אינסטלציה כהן",
    "slug": "cohen-plumbing",
    "admin_email": "dana@cohen.example",
    "admin_password": "correct-horse-battery",
}


def business_count(db: Session, slug: str) -> int:
    return db.scalar(
        select(func.count()).select_from(Business).where(Business.slug == slug)
    )


def user_count(db: Session, email: str) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.email == email)
    )


def test_onboarding_creates_business_and_admin_who_can_log_in(
    client: TestClient,
    db_session: Session,
) -> None:
    result = create_business_with_admin(db_session, **VALID)

    business = db_session.get(Business, result.business_id)
    admin = db_session.get(User, result.admin_user_id)

    assert business.name == VALID["name"]
    assert business.slug == VALID["slug"]
    assert admin.business_id == business.id
    assert admin.role == ROLE_ADMIN

    login_response = client.post(
        "/login",
        json={
            "email": VALID["admin_email"],
            "password": VALID["admin_password"],
        },
    )

    assert login_response.status_code == 200


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": "   "}, "must not be empty"),
        ({"name": "א" * 201}, "at most 200 characters"),
        ({"slug": "Cohen Plumbing"}, "is invalid"),
        ({"slug": "כהן"}, "is invalid"),
        ({"slug": "a" * 64}, "is invalid"),
        ({"admin_email": "not-an-email"}, "is invalid"),
        ({"admin_password": "short"}, "at least 12 characters"),
    ],
)
def test_invalid_input_is_rejected_and_nothing_is_saved(
    db_session: Session,
    overrides: dict[str, str],
    message: str,
) -> None:
    data = {**VALID, **overrides}

    with pytest.raises(OnboardingError, match=message):
        create_business_with_admin(db_session, **data)

    assert business_count(db_session, data["slug"].strip()) == 0
    assert user_count(db_session, data["admin_email"].strip()) == 0


def test_duplicate_slug_is_rejected(db_session: Session) -> None:
    create_business_with_admin(db_session, **VALID)

    with pytest.raises(OnboardingError, match="already used"):
        create_business_with_admin(
            db_session,
            **{**VALID, "admin_email": "other@cohen.example"},
        )

    assert business_count(db_session, VALID["slug"]) == 1
    assert user_count(db_session, "other@cohen.example") == 0


def test_taken_email_does_not_leave_a_business_without_admin(
    db_session: Session,
) -> None:
    create_business_with_admin(db_session, **VALID)

    with pytest.raises(OnboardingError, match="already registered"):
        create_business_with_admin(
            db_session,
            **{**VALID, "slug": "cohen-electric"},
        )

    assert business_count(db_session, "cohen-electric") == 0


def test_hebrew_name_is_stored_in_normalized_form(db_session: Session) -> None:
    # Kaf with dagesh and holam: keyboards may type the two marks in either order.
    # Both look identical but differ as stored text.
    dagesh_first = "כֹּהן"
    holam_first = "כֹּהן"

    # Guard: the test is only meaningful if the input is not already normalized.
    assert unicodedata.normalize("NFC", dagesh_first) != dagesh_first

    result = create_business_with_admin(
        db_session,
        **{**VALID, "name": f"  {dagesh_first}  "},
    )

    assert db_session.get(Business, result.business_id).name == holam_first


def test_users_created_without_role_are_members(
    db_session: Session,
    test_business: Business,
) -> None:
    user = User(
        email="member@example.com",
        hashed_password="not-a-real-hash",
        business=test_business,
    )
    db_session.add(user)
    db_session.flush()
    db_session.refresh(user)

    assert user.role == ROLE_MEMBER


def test_database_rejects_unknown_role(
    db_session: Session,
    test_business: Business,
) -> None:
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                User(
                    email="owner@example.com",
                    hashed_password="not-a-real-hash",
                    business=test_business,
                    role="owner",
                )
            )
