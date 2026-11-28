import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.accounts import grant_task_edit
from app.backend.models import ROLE_ADMIN, AuditEvent, Business, Task, User


SLUG = "test-business"
NAMES = ("dana", "eli", "ori", "gal", "avi", "noa")


@pytest.fixture
def team(
    db_session: Session, auth_headers_factory, user_factory, other_business: Business
) -> dict:
    """Dana leads; Eli edits own tasks, Ori all, Gal Avi's (edit grant); Avi and Noa are members."""
    headers = {
        name: auth_headers_factory(
            f"{name}@example.com", role=ROLE_ADMIN if name in ("dana", "eli", "ori", "gal") else "member"
        )
        for name in NAMES
    }
    users = {
        name: db_session.scalar(select(User).where(User.email == f"{name}@example.com"))
        for name in NAMES
    }
    users["ori"].edits_all_tasks = True
    grant_task_edit(
        db_session, business_slug=SLUG, viewer_email="gal@example.com", owner_email="avi@example.com"
    )
    boss = user_factory("boss@other.example", role=ROLE_ADMIN, business=other_business)
    tasks = {name: [add_task(db_session, user), add_task(db_session, user)] for name, user in users.items()}
    return {
        "headers": headers,
        "users": users,
        "tasks": tasks,
        "boss": boss,
        "outsider_task": add_task(db_session, boss),
    }


def add_task(db: Session, owner: User) -> Task:
    task = Task(title="A task", owner=owner, business_id=owner.business_id)
    db.add(task)
    db.flush()
    return task


def owner_of(db: Session, task: Task) -> int:
    return db.scalar(select(Task.owner_id).where(Task.id == task.id))


def move_user(client: TestClient, team: dict, actor: str, source: str, receiver_id: int):
    return client.post(
        f"/business/users/{team['users'][source].id}/reassign-tasks",
        headers=team["headers"][actor],
        json={"to_user_id": receiver_id},
    )


def move_chosen(client: TestClient, team: dict, actor: str, task_ids: list[int], receiver: str):
    return client.post(
        "/business/tasks/reassign",
        headers=team["headers"][actor],
        json={"task_ids": task_ids, "to_user_id": team["users"][receiver].id},
    )


@pytest.mark.parametrize(
    ("actor", "source", "receiver"),
    [
        ("dana", "avi", "eli"),
        # Editing all includes the leader's tasks, and any receiver, admins included.
        ("ori", "dana", "eli"),
        # An edit grant on Avi is enough to move Avi's tasks.
        ("gal", "avi", "eli"),
    ],
)
def test_moving_all_of_a_users_tasks(
    client: TestClient, db_session: Session, team: dict, actor: str, source: str, receiver: str
) -> None:
    response = move_user(client, team, actor, source, team["users"][receiver].id)

    assert response.status_code == 200
    assert response.json()["tasks_moved"] == 2
    assert {owner_of(db_session, task) for task in team["tasks"][source]} == {
        team["users"][receiver].id
    }


@pytest.mark.parametrize(
    ("actor", "source", "receiver", "status"),
    [
        ("eli", "avi", "noa", 403),
        # Members move nothing, not even their own tasks.
        ("avi", "avi", "noa", 403),
        ("dana", "avi", "boss", 404),
        ("dana", "avi", "avi", 400),
    ],
)
def test_refused_user_moves_change_nothing(
    client: TestClient,
    db_session: Session,
    team: dict,
    actor: str,
    source: str,
    receiver: str,
    status: int,
) -> None:
    receiver_id = team["boss"].id if receiver == "boss" else team["users"][receiver].id

    response = move_user(client, team, actor, source, receiver_id)

    assert response.status_code == status
    assert {owner_of(db_session, task) for task in team["tasks"][source]} == {
        team["users"][source].id
    }


def test_moving_chosen_tasks_from_several_owners(
    client: TestClient, db_session: Session, team: dict
) -> None:
    avi_task, noa_task = team["tasks"]["avi"][0], team["tasks"]["noa"][0]

    response = move_chosen(client, team, "ori", [avi_task.id, noa_task.id], "eli")

    assert response.status_code == 200
    assert response.json()["tasks_moved"] == 2
    eli_id = team["users"]["eli"].id
    assert (owner_of(db_session, avi_task), owner_of(db_session, noa_task)) == (eli_id, eli_id)
    # The other tasks stay where they were.
    assert owner_of(db_session, team["tasks"]["avi"][1]) == team["users"]["avi"].id
    event = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "tasks_reassigned")
    ).one()
    assert event.actor_email == "ori@example.com"


def test_moving_chosen_tasks_is_all_or_nothing(
    client: TestClient, db_session: Session, team: dict
) -> None:
    # Gal may change Avi's tasks, not Noa's.
    avi_task, noa_task = team["tasks"]["avi"][0], team["tasks"]["noa"][0]

    response = move_chosen(client, team, "gal", [avi_task.id, noa_task.id], "eli")

    assert response.status_code == 403
    assert owner_of(db_session, avi_task) == team["users"]["avi"].id
    assert owner_of(db_session, noa_task) == team["users"]["noa"].id


@pytest.mark.parametrize("which", ["unknown", "outsider"])
def test_tasks_the_caller_cannot_see_are_not_found(
    client: TestClient, db_session: Session, team: dict, which: str
) -> None:
    avi_task = team["tasks"]["avi"][0]
    other_id = 999_999_999 if which == "unknown" else team["outsider_task"].id

    response = move_chosen(client, team, "dana", [avi_task.id, other_id], "eli")

    assert response.status_code == 404
    assert owner_of(db_session, avi_task) == team["users"]["avi"].id


@pytest.mark.parametrize("count", [0, 501])
def test_task_lists_must_have_1_to_500_ids(client: TestClient, team: dict, count: int) -> None:
    response = move_chosen(client, team, "dana", list(range(1, count + 1)), "eli")

    assert response.status_code == 422


def test_repeated_ids_move_one_task(client: TestClient, db_session: Session, team: dict) -> None:
    avi_task = team["tasks"]["avi"][0]

    response = move_chosen(client, team, "dana", [avi_task.id, avi_task.id], "eli")

    assert response.status_code == 200
    assert response.json()["tasks_moved"] == 1
