import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.accounts import add_user, reset_password
from app.backend.main import app
from app.backend.models import AuditEvent, User
from app.backend.onboarding import create_business_with_admin


LOGIN = "/businesses/test-business/login"
EMAIL = "avi@example.com"
PASSWORD = "temporary-password-1"


def in_days(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


@pytest.fixture
def avi(db_session: Session, user_factory) -> User:
    """A user with a temporary password that is still valid."""
    user = user_factory(EMAIL, password=PASSWORD)
    user.temporary_password_expires_at = in_days(7)
    db_session.flush()
    return user


def login(client: TestClient, password: str = PASSWORD):
    return client.post(LOGIN, json={"email": EMAIL, "password": password})


@pytest.mark.parametrize("temporary", [True, False])
def test_login_and_me_say_whether_the_password_must_be_changed(
    client: TestClient, db_session: Session, avi: User, temporary: bool
) -> None:
    if not temporary:
        avi.temporary_password_expires_at = None
        db_session.flush()

    response = login(client)

    assert response.status_code == 200
    assert response.json()["must_change_password"] is temporary
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.get("/me", headers=headers).json()["must_change_password"] is temporary


def test_expired_temporary_password_is_refused_only_to_someone_who_knows_it(
    client: TestClient, db_session: Session, avi: User
) -> None:
    wrong_before = login(client, "wrong-password-1")
    avi.temporary_password_expires_at = in_days(-1)
    db_session.flush()

    expired = login(client)
    wrong_after = login(client, "wrong-password-1")

    assert expired.status_code == 403
    assert "has expired" in expired.json()["detail"]
    assert "access_token" not in expired.json()
    # A guesser cannot tell that the account's password has expired.
    assert wrong_after.status_code == wrong_before.status_code == 401
    assert wrong_after.json() == wrong_before.json()


def test_choosing_a_password_ends_the_temporary_state(
    client: TestClient, db_session: Session, avi: User
) -> None:
    temporary = {"Authorization": f"Bearer {login(client).json()['access_token']}"}

    response = client.put(
        "/me/password",
        headers=temporary,
        json={"current_password": PASSWORD, "new_password": "avis-own-password-1"},
    )

    assert response.status_code == 200
    assert response.json()["must_change_password"] is False
    fresh = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.get("/tasks", headers=fresh).status_code == 200
    assert client.get("/me", headers=fresh).json()["must_change_password"] is False
    assert avi.temporary_password_expires_at is None


def test_only_the_password_change_is_reachable_with_a_temporary_password(
    client: TestClient, avi: User
) -> None:
    headers = {"Authorization": f"Bearer {login(client).json()['access_token']}"}
    public, reachable = set(), set()

    # Listed from the app itself, so an endpoint added later is checked too.
    for path, operations in app.openapi()["paths"].items():
        url = re.sub(r"\{.*?\}", "1", path)
        for method, operation in operations.items():
            endpoint = f"{method.upper()} {path}"
            if "security" not in operation:
                public.add(endpoint)
                continue
            response = client.request(method, url, headers=headers)
            refused = (
                response.status_code == 403
                and response.json()["detail"] == "Change your temporary password first"
            )
            if not refused:
                reachable.add(endpoint)

    assert reachable == {"GET /me", "PUT /me/password"}
    # Named too, so an endpoint that forgets to require a login fails here.
    assert public == {"GET /health", "POST /businesses/{slug}/login"}


OPERATOR_PASSWORD = "chosen-by-operator-1"


def set_by_operator(db: Session, action: str, temporary: bool) -> User:
    if action == "add":
        return add_user(
            db, business_slug="test-business", email="noa@example.com", role="member",
            password=OPERATOR_PASSWORD, temporary=temporary,
        )
    if action == "reset":
        reset_password(
            db, business_slug="test-business", email=EMAIL,
            password=OPERATOR_PASSWORD, temporary=temporary,
        )
        return db.scalar(select(User).where(User.email == EMAIL))
    result = create_business_with_admin(
        db, name="Shop", slug="shop", admin_email="dana@shop.example",
        admin_password=OPERATOR_PASSWORD, temporary=temporary,
    )
    return db.get(User, result.admin_user_id)


@pytest.mark.parametrize("temporary", [True, False])
@pytest.mark.parametrize("action", ["add", "reset", "onboard"])
def test_operator_passwords_are_temporary_unless_permanent(
    db_session: Session, avi: User, action: str, temporary: bool
) -> None:
    before = datetime.now(timezone.utc)

    user = set_by_operator(db_session, action, temporary)

    expires_at = user.temporary_password_expires_at
    if temporary:
        assert before + timedelta(days=7) <= expires_at <= in_days(7)
    else:
        assert expires_at is None
    event = db_session.scalars(select(AuditEvent).order_by(AuditEvent.id.desc())).first()
    assert event.details["temporary"] is temporary


def test_permanent_reset_frees_a_user_whose_temporary_password_expired(
    client: TestClient, db_session: Session, avi: User
) -> None:
    avi.temporary_password_expires_at = in_days(-1)
    db_session.flush()
    assert login(client).status_code == 403

    reset_password(
        db_session, business_slug="test-business", email=EMAIL,
        password=OPERATOR_PASSWORD, temporary=False,
    )

    response = login(client, OPERATOR_PASSWORD)
    assert response.status_code == 200
    assert response.json()["must_change_password"] is False
