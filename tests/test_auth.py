from fastapi.testclient import TestClient


def test_public_registration_is_closed(client: TestClient) -> None:
    response = client.post(
        "/register",
        json={
            "email": "alice@example.com",
            "password": "password123",
        },
    )

    assert response.status_code == 404


def test_login_user(client: TestClient, user_factory) -> None:
    user_factory("alice@example.com", "password123")

    login_response = client.post(
        "/login",
        json={
            "email": "alice@example.com",
            "password": "password123",
        },
    )

    assert login_response.status_code == 200

    data = login_response.json()

    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_with_wrong_password_is_rejected(
    client: TestClient,
    user_factory,
) -> None:
    user_factory("alice@example.com", "password123")

    response = client.post(
        "/login",
        json={
            "email": "alice@example.com",
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401


def test_unknown_email_gets_the_same_response_as_wrong_password(
    client: TestClient,
    user_factory,
) -> None:
    user_factory("alice@example.com", "password123")

    wrong_password = client.post(
        "/login",
        json={
            "email": "alice@example.com",
            "password": "wrong-password",
        },
    )
    unknown_email = client.post(
        "/login",
        json={
            "email": "nobody@example.com",
            "password": "password123",
        },
    )

    # Identical answers do not reveal which emails have accounts.
    assert unknown_email.status_code == wrong_password.status_code == 401
    assert unknown_email.json() == wrong_password.json()
