from fastapi.testclient import TestClient


def test_create_task(
        client: TestClient,
        auth_headers_factory,
) -> None:
    headers = auth_headers_factory("alice@example.com")
    response = client.post(
        "/tasks",
        json={
            "title": "Learn pytest fixtures",
        },
        headers=headers,
    )

    assert response.status_code ==201

    data = response.json()

    assert data["title"] == "Learn pytest fixtures"
    assert data["completed"] is False
    assert "id" in data


def test_create_task_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/tasks",
        json={
            "title": "Unauthorized task",
        },
    )

    assert response.status_code == 401


def test_user_cannot_update_another_users_task(
    client: TestClient,
    auth_headers_factory,
) -> None:
    alice_headers = auth_headers_factory("alice@example.com")
    bob_headers = auth_headers_factory("bob@example.com")

    create_response = client.post(
        "/tasks",
        json={
            "title": "Alice's private task",
        },
        headers=alice_headers,
    )

    assert create_response.status_code == 201

    task_id = create_response.json()["id"]

    update_response = client.patch(
        f"/tasks/{task_id}",
        json={
            "title": "Bob changed this task",
        },
        headers=bob_headers,
    )

    assert update_response.status_code == 404

    get_response = client.get(
        f"/tasks/{task_id}",
        headers=alice_headers,
    )

    assert get_response.status_code == 200
    assert get_response.json()["title"] == "Alice's private task"


def test_user_cannot_delete_another_users_task(
    client: TestClient,
    auth_headers_factory, 
) -> None:
    alice_headers = auth_headers_factory("alice@example.com")
    bob_headers = auth_headers_factory("bob@example.com")

    create_response = client.post(
        "/tasks",
        json={
            "title": "Alice's private task",
        },
        headers=alice_headers,
    )

    assert create_response.status_code == 201

    task_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/tasks/{task_id}",
        headers=bob_headers,
    )

    assert delete_response.status_code == 404

    get_response = client.get(
        f"/tasks/{task_id}",
        headers=alice_headers,
    )

    assert get_response.status_code == 200
    assert get_response.json()["title"] == "Alice's private task"


def test_user_cannot_read_another_users_task(
    client: TestClient,
    auth_headers_factory,
) -> None:
    alice_headers = auth_headers_factory("alice@example.com")
    bob_headers = auth_headers_factory("bob@example.com")

    create_response = client.post(
        "/tasks",
        json={
            "title": "Alice's private task",
        },
        headers=alice_headers,
    )

    assert create_response.status_code == 201

    task_id = create_response.json()["id"]

    get_response = client.get(
        f"/tasks/{task_id}",
        headers=bob_headers,
    )

    assert get_response.status_code == 404


def test_user_only_sees_their_own_tasks(
    client: TestClient,
    auth_headers_factory,
) -> None:
    alice_headers = auth_headers_factory("alice@example.com")
    bob_headers = auth_headers_factory("bob@example.com")

    client.post(
        "/tasks",
        json={"title": "Alice's task"},
        headers=alice_headers,
    )

    client.post(
        "/tasks",
        json={"title": "Bob's task"},
        headers=bob_headers,
    )

    alice_response = client.get(
        "/tasks",
        headers=alice_headers,
    )

    assert alice_response.status_code == 200

    alice_tasks = alice_response.json()

    assert len(alice_tasks) == 1
    assert alice_tasks[0]["title"] == "Alice's task"