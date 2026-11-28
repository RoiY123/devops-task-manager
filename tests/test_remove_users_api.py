import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.accounts import grant_task_edit
from app.backend.models import ROLE_ADMIN, AuditEvent, Business, Task, User


SLUG = "test-business"
ADMINS = ("dana", "eli", "ori", "gal")
NAMES = (*ADMINS, "avi", "noa", "zoe")
# Zoe has no tasks; Noa has one, so a message about her count reads "1 task".
TASK_COUNTS = {"dana": 2, "eli": 2, "ori": 2, "gal": 2, "avi": 2, "noa": 1, "zoe": 0}


@pytest.fixture
def team(
    db_session: Session, auth_headers_factory, user_factory, other_business: Business
) -> dict:
    """Dana leads; Eli edits own tasks, Ori all, Gal Avi's (edit grant); the rest are members."""
    headers = {
        name: auth_headers_factory(
            f"{name}@example.com", role=ROLE_ADMIN if name in ADMINS else "member"
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
    for name, count in TASK_COUNTS.items():
        db_session.add_all(
            [
                Task(title="A task", owner=users[name], business_id=users[name].business_id)
                for _ in range(count)
            ]
        )
    users["boss"] = user_factory("boss@other.example", role=ROLE_ADMIN, business=other_business)
    db_session.flush()
    # Ids now: a removed user's object cannot be read afterwards.
    return {"headers": headers, "ids": {name: user.id for name, user in users.items()}}


def remove(client: TestClient, team: dict, actor: str, target: str, params: dict):
    return client.delete(
        f"/business/users/{team['ids'][target]}",
        headers=team["headers"][actor],
        params=params,
    )


def tasks_of(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Task).where(Task.owner_id == user_id))


def exists(db: Session, user_id: int) -> bool:
    return db.scalar(select(func.count()).select_from(User).where(User.id == user_id)) == 1


@pytest.mark.parametrize(
    ("actor", "target", "option", "deleted", "reassigned"),
    [
        ("dana", "eli", {"delete_tasks": "true"}, 2, 0),
        ("dana", "avi", {"reassign_to": "noa"}, 0, 2),
        ("ori", "avi", {"delete_tasks": "true"}, 2, 0),
        # An edit grant on Avi is enough to decide about Avi's tasks.
        ("gal", "avi", {"reassign_to": "eli"}, 0, 2),
        # No tasks: any admin may remove a member, without an option.
        ("eli", "zoe", {}, 0, 0),
    ],
)
def test_allowed_removals(
    client: TestClient,
    db_session: Session,
    team: dict,
    actor: str,
    target: str,
    option: dict,
    deleted: int,
    reassigned: int,
) -> None:
    ids = team["ids"]
    params = {key: ids.get(value, value) for key, value in option.items()}
    receiver_before = tasks_of(db_session, ids[option["reassign_to"]]) if "reassign_to" in option else 0

    response = remove(client, team, actor, target, params)

    assert response.status_code == 200
    assert response.json()["tasks_deleted"] == deleted
    assert response.json()["tasks_reassigned"] == reassigned
    assert not exists(db_session, ids[target])
    if "reassign_to" in option:
        assert tasks_of(db_session, ids[option["reassign_to"]]) == receiver_before + reassigned
    event = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "user_removed")
    ).one()
    assert event.actor_email == f"{actor}@example.com"
    # The removed user's login stops working at once.
    assert client.get("/me", headers=team["headers"][target]).status_code == 401


@pytest.mark.parametrize(
    ("actor", "target", "option", "status", "detail"),
    [
        ("eli", "avi", {"delete_tasks": "true"}, 403, "only if you can change them"),
        ("eli", "avi", {"reassign_to": "noa"}, 403, "only if you can change them"),
        ("eli", "ori", {"delete_tasks": "true"}, 403, "Admins can remove only members"),
        ("avi", "noa", {"delete_tasks": "true"}, 403, "Only the leader and admins"),
        ("dana", "dana", {}, 403, "cannot remove yourself"),
        ("ori", "dana", {}, 403, "Only the operator"),
        ("dana", "avi", {}, 400, "has 2 tasks: choose"),
        ("dana", "noa", {}, 400, "has 1 task: choose"),
        ("dana", "avi", {"delete_tasks": "true", "reassign_to": "noa"}, 400, "choose"),
        ("dana", "avi", {"reassign_to": "avi"}, 400, "Choose another user"),
        ("dana", "avi", {"reassign_to": "boss"}, 404, "User not found"),
    ],
)
def test_refused_removals_change_nothing(
    client: TestClient,
    db_session: Session,
    team: dict,
    actor: str,
    target: str,
    option: dict,
    status: int,
    detail: str,
) -> None:
    ids = team["ids"]
    params = {key: ids.get(value, value) for key, value in option.items()}

    response = remove(client, team, actor, target, params)

    assert response.status_code == status
    assert detail in response.json()["detail"]
    assert exists(db_session, ids[target])
    assert tasks_of(db_session, ids[target]) == TASK_COUNTS[target]
