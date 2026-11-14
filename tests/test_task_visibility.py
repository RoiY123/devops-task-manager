import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.backend.models import ROLE_ADMIN, Business, Task


@pytest.fixture
def other_business(db_session: Session) -> Business:
    business = Business(name="עסק אחר", slug="other-business")
    db_session.add(business)
    db_session.flush()
    return business


def create_task(client: TestClient, headers: dict[str, str], title: str) -> dict:
    response = client.post("/tasks", json={"title": title}, headers=headers)
    assert response.status_code == 201
    return response.json()


def titles(client: TestClient, headers: dict[str, str]) -> set[str]:
    response = client.get("/tasks", headers=headers)
    assert response.status_code == 200
    return {task["title"] for task in response.json()}


def test_admin_sees_every_task_in_the_business(
    client: TestClient, auth_headers_factory
) -> None:
    avi = auth_headers_factory("avi@example.com")
    dana = auth_headers_factory("dana@example.com", role=ROLE_ADMIN)
    avi_task = create_task(client, avi, "Avi's task")
    create_task(client, dana, "Dana's task")

    assert titles(client, dana) == {"Avi's task", "Dana's task"}
    assert titles(client, avi) == {"Avi's task"}
    assert (
        client.get(f"/tasks/{avi_task['id']}", headers=dana).json()["owner_id"]
        == avi_task["owner_id"]
    )


def test_admin_limited_to_own_tasks_sees_only_them(
    client: TestClient, auth_headers_factory
) -> None:
    avi = auth_headers_factory("avi@example.com")
    dana = auth_headers_factory(
        "dana@example.com", role=ROLE_ADMIN, sees_all_tasks=False
    )
    avi_task = create_task(client, avi, "Avi's task")
    create_task(client, dana, "Dana's task")

    assert titles(client, dana) == {"Dana's task"}
    assert client.get(f"/tasks/{avi_task['id']}", headers=dana).status_code == 404


def test_member_who_sees_all_can_view_but_not_change_others_tasks(
    client: TestClient, auth_headers_factory
) -> None:
    avi = auth_headers_factory("avi@example.com")
    noa = auth_headers_factory("noa@example.com", sees_all_tasks=True)
    avi_task = create_task(client, avi, "Avi's task")
    url = f"/tasks/{avi_task['id']}"

    assert client.get(url, headers=noa).status_code == 200
    assert client.patch(url, json={"completed": True}, headers=noa).status_code == 403
    assert client.delete(url, headers=noa).status_code == 403
    assert client.get(url, headers=avi).json()["completed"] is False


def test_admin_can_change_and_delete_a_visible_task(
    client: TestClient, auth_headers_factory
) -> None:
    avi = auth_headers_factory("avi@example.com")
    dana = auth_headers_factory("dana@example.com", role=ROLE_ADMIN)
    url = f"/tasks/{create_task(client, avi, 'Avi task')['id']}"

    assert (
        client.patch(url, json={"completed": True}, headers=dana).json()["completed"]
        is True
    )
    assert client.delete(url, headers=dana).status_code == 204
    assert client.get(url, headers=avi).status_code == 404


def test_tasks_never_cross_businesses(
    client: TestClient, auth_headers_factory, other_business: Business
) -> None:
    avi = auth_headers_factory("avi@example.com")
    outsider = auth_headers_factory(
        "boss@other.example", role=ROLE_ADMIN, business=other_business
    )
    avi_task = create_task(client, avi, "Avi's task")

    assert titles(client, outsider) == set()
    assert client.get(f"/tasks/{avi_task['id']}", headers=outsider).status_code == 404


def test_new_task_records_its_owners_business(
    client: TestClient,
    db_session: Session,
    auth_headers_factory,
    test_business: Business,
) -> None:
    avi = auth_headers_factory("avi@example.com")

    task_id = create_task(client, avi, "Avi's task")["id"]

    assert db_session.get(Task, task_id).business_id == test_business.id
