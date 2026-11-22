from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend import security
from app.backend.models import Business, User


LOGIN = "/businesses/test-business/login"
ALICE = {"email": "alice@example.com", "password": "password123"}


@pytest.fixture
def alice(user_factory) -> None:
    user_factory(ALICE["email"], ALICE["password"])


def test_public_registration_is_closed(client: TestClient) -> None:
    assert client.post("/register", json=ALICE).status_code == 404


def test_old_login_endpoint_is_gone(client: TestClient, alice) -> None:
    assert client.post("/login", json=ALICE).status_code == 404


def test_login_in_the_users_business(client: TestClient, alice) -> None:
    response = client.post(LOGIN, json=ALICE)

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_login_ignores_email_capitals_and_spaces(client: TestClient, alice) -> None:
    response = client.post(
        LOGIN, json={**ALICE, "email": "  Alice@Example.COM "}
    )

    assert response.status_code == 200


def test_every_failed_login_gets_the_same_response(
    client: TestClient,
    db_session: Session,
    alice,
) -> None:
    db_session.add(Business(name="עסק אחר", slug="other-business"))
    db_session.flush()

    failures = [
        client.post(LOGIN, json={**ALICE, "password": "wrong-password"}),
        client.post(LOGIN, json={**ALICE, "email": "nobody@example.com"}),
        client.post("/businesses/other-business/login", json=ALICE),
        client.post("/businesses/no-such-business/login", json=ALICE),
    ]

    # Identical answers do not reveal which emails or businesses exist.
    assert {response.status_code for response in failures} == {401}
    assert all(response.json() == failures[0].json() for response in failures)


def test_unknown_email_still_checks_a_password(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    alice,
) -> None:
    calls = []
    real_verify = security.password_hash.verify

    def counting_verify(*args, **kwargs):
        calls.append(args)
        return real_verify(*args, **kwargs)

    monkeypatch.setattr(security.password_hash, "verify", counting_verify)

    client.post(LOGIN, json={**ALICE, "email": "nobody@example.com"})

    # The check against the dummy hash makes this as slow as a real failure.
    assert len(calls) == 1


CUT_OFF = datetime(2026, 11, 22, 10, 0, 0, 700000, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("cut_off", "issued_at", "status"),
    [
        (None, CUT_OFF - timedelta(minutes=10), 200),
        (CUT_OFF, CUT_OFF - timedelta(minutes=10), 401),
        # Same second as the cut-off: the fresh token handed out with a password change.
        (CUT_OFF, CUT_OFF.replace(microsecond=0), 200),
        (CUT_OFF, CUT_OFF + timedelta(minutes=1), 200),
        # Issued by an image from before iat existed.
        (None, None, 200),
        (CUT_OFF, None, 401),
    ],
)
def test_tokens_issued_before_the_cut_off_are_refused(
    client: TestClient,
    db_session: Session,
    user_factory,
    token_headers,
    cut_off: datetime | None,
    issued_at: datetime | None,
    status: int,
) -> None:
    alice = user_factory(ALICE["email"], ALICE["password"])
    alice.tokens_valid_after = cut_off
    db_session.flush()

    assert client.get("/tasks", headers=token_headers(alice.id, issued_at)).status_code == status


def test_logging_in_right_after_a_cut_off_works(
    client: TestClient, db_session: Session, alice
) -> None:
    user = db_session.scalar(select(User).where(User.email == ALICE["email"]))
    user.tokens_valid_after = datetime.now(timezone.utc)
    db_session.flush()

    access_token = client.post(LOGIN, json=ALICE).json()["access_token"]

    assert client.get("/tasks", headers={"Authorization": f"Bearer {access_token}"}).status_code == 200
