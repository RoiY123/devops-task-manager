import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.backend import security
from app.backend.models import Business


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
