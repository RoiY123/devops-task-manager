from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.models import AuditEvent, User


URL = "/me/password"
LOGIN = "/businesses/test-business/login"
CURRENT = "current-password-123"
NEW = "brand-new-password-456"


@pytest.fixture
def dana(user_factory) -> User:
    return user_factory("dana@example.com", password=CURRENT)


@pytest.fixture
def phone(dana: User, token_headers) -> dict[str, str]:
    # A login from a minute ago; one from the same second would outlive the cut-off.
    return token_headers(dana.id, datetime.now(timezone.utc) - timedelta(minutes=1))


def login_status(client: TestClient, password: str) -> int:
    return client.post(
        LOGIN, json={"email": "dana@example.com", "password": password}
    ).status_code


def test_change_ends_other_logins_and_returns_a_fresh_token(
    client: TestClient, db_session: Session, dana: User, phone: dict[str, str]
) -> None:
    response = client.put(URL, headers=phone, json={"current_password": CURRENT, "new_password": NEW})

    assert response.status_code == 200
    fresh = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.get("/me", headers=fresh).status_code == 200
    assert client.get("/me", headers=phone).status_code == 401
    assert login_status(client, NEW) == 200
    assert login_status(client, CURRENT) == 401

    event = db_session.scalars(select(AuditEvent)).one()
    assert (event.action, event.actor_email, event.target_email, event.details) == (
        "password_changed", "dana@example.com", "dana@example.com", {}
    )


@pytest.mark.parametrize(
    ("current", "new", "reason"),
    [
        ("wrong-password-123", NEW, "Current password is incorrect"),
        (CURRENT, CURRENT, "must differ from the current one"),
        (CURRENT, "a" * 11, "at least 12 characters"),
        (CURRENT, "a" * 257, "at most 256 characters"),
        # The left arrow key's ESC [ D, typed unseen into a password field.
        (CURRENT, NEW + chr(27) + "[D", "control characters"),
    ],
)
def test_refused_change_changes_nothing(
    client: TestClient,
    db_session: Session,
    dana: User,
    phone: dict[str, str],
    current: str,
    new: str,
    reason: str,
) -> None:
    response = client.put(URL, headers=phone, json={"current_password": current, "new_password": new})

    # 400, not 401: the login itself is fine, so the page must not log the user out.
    assert response.status_code == 400
    assert reason in response.json()["detail"]
    assert client.get("/me", headers=phone).status_code == 200
    assert login_status(client, CURRENT) == 200
    assert db_session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_new_password_of_the_maximum_length_is_accepted(
    client: TestClient, dana: User, phone: dict[str, str]
) -> None:
    longest = "a" * 256

    response = client.put(URL, headers=phone, json={"current_password": CURRENT, "new_password": longest})

    assert response.status_code == 200
    assert login_status(client, longest) == 200


def test_change_requires_a_login(client: TestClient, dana: User) -> None:
    response = client.put(URL, json={"current_password": CURRENT, "new_password": NEW})

    assert response.status_code == 401
