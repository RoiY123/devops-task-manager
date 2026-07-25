from fastapi.testclient import TestClient


def test_register_user(client: TestClient) -> None:
    response = client.post(
        "/register",
        json={
            "email": "alice@example.com",
            "password": "password123",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["email"] == "alice@example.com"
    assert "password" not in data

def test_register_duplicate_email(client: TestClient) -> None:
    user_data = {
        "email": "alice@example.com",
        "password": "password123",
    }

    first_response = client.post("/register", json=user_data)
    second_response = client.post("/register", json=user_data)

    assert first_response.status_code == 201
    assert second_response.status_code == 409

def test_login_user(client: TestClient) -> None:
    user_data = {
        "email": "alice@example.com",
        "password": "password123",
    }

    register_response = client.post("/register", json=user_data)

    assert register_response.status_code == 201

    login_response = client.post(
        "/login",
        json=user_data,
    )

    assert login_response.status_code == 200

    data = login_response.json()

    assert "access_token" in data
    assert data["token_type"] == "bearer"