import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.accounts import (
    OperatorError,
    Reassignment,
    grant_task_view,
    reassign_all_tasks,
    reassign_tasks,
)
from app.backend.models import ROLE_ADMIN, AuditEvent, Business, Task, TaskGrant, User
from app.backend.visibility import visible_tasks


SLUG = "test-business"


@pytest.fixture
def team(user_factory) -> dict[str, User]:
    # The first admin becomes the leader.
    return {
        "dana": user_factory("dana@example.com", role=ROLE_ADMIN),
        "avi": user_factory("avi@example.com"),
        "noa": user_factory("noa@example.com"),
        "zoe": user_factory("zoe@example.com"),
    }


def add_tasks(db: Session, owner: User, count: int) -> list[Task]:
    tasks = [
        Task(title=f"Task {number}", owner=owner, business_id=owner.business_id)
        for number in range(count)
    ]
    db.add_all(tasks)
    db.flush()
    return tasks


def owned(db: Session, user: User) -> int:
    return db.scalar(select(func.count()).select_from(Task).where(Task.owner_id == user.id))


def reassigned(db: Session) -> list[AuditEvent]:
    # Grants made in a test are events too; only the moves matter here.
    return list(
        db.scalars(select(AuditEvent).where(AuditEvent.action == "tasks_reassigned"))
    )


def grant(db: Session, viewer: User, owner: User) -> None:
    grant_task_view(
        db, business_slug=SLUG, viewer_email=viewer.email, owner_email=owner.email
    )


def move_all(db: Session, from_email: str, to_email: str) -> Reassignment:
    return reassign_all_tasks(db, business_slug=SLUG, from_email=from_email, to_email=to_email)


def test_all_tasks_move_and_the_move_is_recorded(db_session: Session, team) -> None:
    tasks = add_tasks(db_session, team["avi"], 3)

    result = move_all(db_session, "avi@example.com", "noa@example.com")

    assert result.tasks_moved == 3
    assert (owned(db_session, team["avi"]), owned(db_session, team["noa"])) == (0, 3)
    [event] = reassigned(db_session)
    assert (event.actor_kind, event.target_email) == ("operator", "noa@example.com")
    assert event.details == {
        "task_ids": sorted(task.id for task in tasks),
        "from_owners": {"avi@example.com": 3},
    }


def add_grant(db: Session, viewer: User, owner: User, permission: str) -> None:
    # Inserted directly: the account functions refuse some of these combinations,
    # which older data may still hold.
    db.add(
        TaskGrant(
            viewer_id=viewer.id, owner_id=owner.id,
            business_id=owner.business_id, permission=permission,
        )
    )
    db.flush()


@pytest.mark.parametrize(
    ("holder", "on_avi", "on_noa", "counted"),
    [
        ("zoe", "view", None, True),
        # Still sees the tasks, but can no longer change them.
        ("zoe", "edit", "view", True),
        ("zoe", "view", "view", False),
        ("zoe", "edit", "edit", False),
        # An admin sees all tasks anyway; the edit grant was the only way to change them.
        ("gal", "edit", None, True),
        # Editing all keeps every access, whoever owns the tasks.
        ("ori", "edit", None, False),
        # The receiver owns the tasks afterwards.
        ("noa", "view", None, False),
    ],
)
def test_people_losing_access_are_counted_and_grants_stay(
    db_session: Session,
    team,
    user_factory,
    holder: str,
    on_avi: str,
    on_noa: str | None,
    counted: bool,
) -> None:
    team["gal"] = user_factory("gal@example.com", role=ROLE_ADMIN)
    team["ori"] = user_factory("ori@example.com", role=ROLE_ADMIN)
    team["ori"].edits_all_tasks = True
    add_tasks(db_session, team["avi"], 2)
    add_grant(db_session, team[holder], team["avi"], on_avi)
    if on_noa:
        add_grant(db_session, team[holder], team["noa"], on_noa)

    result = move_all(db_session, "avi@example.com", "noa@example.com")

    assert result.people_losing_access == (1 if counted else 0)
    # Grants do not move with the tasks.
    grant_row = db_session.get(TaskGrant, (team[holder].id, team["avi"].id))
    assert grant_row is not None and grant_row.permission == on_avi


def test_a_viewer_without_a_grant_on_the_receiver_stops_seeing_the_tasks(
    db_session: Session, team
) -> None:
    add_tasks(db_session, team["avi"], 2)
    grant(db_session, team["zoe"], team["avi"])

    move_all(db_session, "avi@example.com", "noa@example.com")

    zoe_sees = db_session.scalar(
        select(func.count()).select_from(Task).where(visible_tasks(team["zoe"]))
    )
    assert zoe_sees == 0


def test_specific_tasks_from_several_owners(db_session: Session, team) -> None:
    avi_tasks = add_tasks(db_session, team["avi"], 2)
    [noa_task] = add_tasks(db_session, team["noa"], 1)
    [zoe_task] = add_tasks(db_session, team["zoe"], 1)

    result = reassign_tasks(
        db_session,
        tasks=[avi_tasks[0], noa_task, zoe_task],
        receiver=team["zoe"],
        actor=team["dana"],
    )

    # Zoe's own task is not a move.
    assert result.tasks_moved == 2
    assert owned(db_session, team["avi"]) == 1
    [event] = reassigned(db_session)
    assert event.actor_email == "dana@example.com"
    assert event.details == {
        "task_ids": sorted([avi_tasks[0].id, noa_task.id]),
        "from_owners": {"avi@example.com": 1, "noa@example.com": 1},
    }


def test_nothing_to_move_records_nothing(db_session: Session, team) -> None:
    result = move_all(db_session, "avi@example.com", "noa@example.com")

    assert result == Reassignment(tasks_moved=0, people_losing_access=0)
    assert reassigned(db_session) == []


@pytest.mark.parametrize(
    ("to_email", "message"),
    [
        ("avi@example.com", "already owns these tasks"),
        ("nobody@example.com", "No user"),
        # Found only in its own business.
        ("boss@other.example", "No user"),
    ],
)
def test_refused_moves_change_nothing(
    db_session: Session,
    team,
    user_factory,
    other_business: Business,
    to_email: str,
    message: str,
) -> None:
    user_factory("boss@other.example", role=ROLE_ADMIN, business=other_business)
    add_tasks(db_session, team["avi"], 2)

    with pytest.raises(OperatorError, match=message):
        move_all(db_session, "avi@example.com", to_email)

    assert owned(db_session, team["avi"]) == 2
    assert reassigned(db_session) == []
