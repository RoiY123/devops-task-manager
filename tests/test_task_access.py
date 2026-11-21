import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.accounts import (
    grant_task_edit,
    grant_task_view,
    revoke_task_edit,
    revoke_task_view,
    set_task_editing,
    set_task_visibility,
)
from app.backend.models import ROLE_ADMIN, ROLE_MEMBER, Business, Task, User


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
    # The leader sees everything anyway, so the admin under test is a second one.
    auth_headers_factory("boss@example.com", role=ROLE_ADMIN)
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


def test_admin_sees_every_task_but_by_default_changes_only_their_own(
    client: TestClient, auth_headers_factory
) -> None:
    # The leader edits everything, so the admin under test is a second one.
    auth_headers_factory("boss@example.com", role=ROLE_ADMIN)
    avi = auth_headers_factory("avi@example.com")
    dana = auth_headers_factory("dana@example.com", role=ROLE_ADMIN)
    url = f"/tasks/{create_task(client, avi, 'Avi task')['id']}"

    assert client.get(url, headers=dana).status_code == 200
    assert client.patch(url, json={"completed": True}, headers=dana).status_code == 403
    assert client.delete(url, headers=dana).status_code == 403


def test_leader_sees_and_changes_every_task_even_if_demoted_by_an_old_image(
    client: TestClient, db_session: Session, auth_headers_factory
) -> None:
    dana_headers = auth_headers_factory("dana@example.com", role=ROLE_ADMIN)
    avi = auth_headers_factory("avi@example.com")
    url = f"/tasks/{create_task(client, avi, 'Avi task')['id']}"
    # What an image from before the leader migration could do: demote the leader.
    dana = db_session.scalar(select(User).where(User.email == "dana@example.com"))
    dana.role, dana.sees_all_tasks = ROLE_MEMBER, False
    db_session.flush()

    assert titles(client, dana_headers) == {"Avi task"}
    assert client.patch(url, json={"completed": True}, headers=dana_headers).status_code == 200


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


def test_leader_can_change_and_delete_any_task(
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


def grant(db: Session, viewer: str, owner: str) -> None:
    grant_task_view(
        db, business_slug="test-business", viewer_email=viewer, owner_email=owner
    )


def test_granted_viewer_sees_owners_tasks_but_cannot_change_them(
    client: TestClient, db_session: Session, auth_headers_factory
) -> None:
    avi = auth_headers_factory("avi@example.com")
    noa = auth_headers_factory("noa@example.com")
    eli = auth_headers_factory("eli@example.com")
    avi_url = f"/tasks/{create_task(client, avi, 'Avi task')['id']}"
    eli_url = f"/tasks/{create_task(client, eli, 'Eli task')['id']}"

    grant(db_session, "noa@example.com", "avi@example.com")

    assert titles(client, noa) == {"Avi task"}
    assert client.get(avi_url, headers=noa).status_code == 200
    assert client.patch(avi_url, json={"completed": True}, headers=noa).status_code == 403
    assert client.get(eli_url, headers=noa).status_code == 404
    # A grant is one-way: Avi still sees only his own tasks.
    assert titles(client, avi) == {"Avi task"}


def test_revoked_grant_hides_the_tasks_again(
    client: TestClient, db_session: Session, auth_headers_factory
) -> None:
    avi = auth_headers_factory("avi@example.com")
    noa = auth_headers_factory("noa@example.com")
    avi_url = f"/tasks/{create_task(client, avi, 'Avi task')['id']}"
    grant(db_session, "noa@example.com", "avi@example.com")

    revoke_task_view(
        db_session,
        business_slug="test-business",
        viewer_email="noa@example.com",
        owner_email="avi@example.com",
    )

    assert titles(client, noa) == set()
    assert client.get(avi_url, headers=noa).status_code == 404


def give_noa(db: Session, setup: str) -> None:
    """Give Noa one kind of access to Avi's tasks, the way the operator would."""
    pair = {
        "business_slug": "test-business",
        "viewer_email": "noa@example.com",
        "owner_email": "avi@example.com",
    }
    user = {"business_slug": "test-business", "email": "noa@example.com"}

    if setup == "edits all":
        set_task_visibility(db, **user, sees_all=True)
        set_task_editing(db, **user, edits_all=True)
    if setup in ("edit grant", "view grant", "edit grant revoked"):
        grant_task_view(db, **pair)
    if setup in ("edit grant", "edit grant revoked"):
        grant_task_edit(db, **pair)
    if setup == "edit grant revoked":
        revoke_task_edit(db, **pair)


@pytest.mark.parametrize(
    ("setup", "noa_role", "change_status"),
    [
        ("edits all", ROLE_MEMBER, 200),
        ("edit grant", ROLE_MEMBER, 200),
        ("view grant", ROLE_MEMBER, 403),
        ("nothing", ROLE_ADMIN, 403),
        # Revoking editing keeps the view: still visible, no longer changeable.
        ("edit grant revoked", ROLE_MEMBER, 403),
    ],
)
def test_who_may_change_another_users_task(
    client: TestClient,
    db_session: Session,
    auth_headers_factory,
    setup: str,
    noa_role: str,
    change_status: int,
) -> None:
    # A leader first, so an admin Noa is an ordinary admin.
    auth_headers_factory("boss@example.com", role=ROLE_ADMIN)
    avi = auth_headers_factory("avi@example.com")
    noa = auth_headers_factory("noa@example.com", role=noa_role)
    url = f"/tasks/{create_task(client, avi, 'Avi task')['id']}"

    give_noa(db_session, setup)

    assert client.get(url, headers=noa).status_code == 200
    assert client.patch(url, json={"completed": True}, headers=noa).status_code == change_status
    assert client.delete(url, headers=noa).status_code == (
        204 if change_status == 200 else 403
    )
