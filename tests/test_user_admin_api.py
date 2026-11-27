from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.backend.models import ROLE_ADMIN, AuditEvent, User


LOGIN = "/businesses/test-business/login"


@pytest.fixture
def headers(auth_headers_factory) -> dict[str, dict[str, str]]:
    return {
        "dana": auth_headers_factory("dana@example.com", role=ROLE_ADMIN),  # the leader
        "eli": auth_headers_factory("eli@example.com", role=ROLE_ADMIN),
        "avi": auth_headers_factory("avi@example.com"),
    }


def user_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User))


@pytest.mark.parametrize("role", ["admin", "member"])
@pytest.mark.parametrize("actor", ["dana", "eli"])
def test_leader_and_admins_add_users_with_a_temporary_password(
    client: TestClient, db_session: Session, headers, actor: str, role: str
) -> None:
    response = client.post(
        "/business/users", headers=headers[actor], json={"email": "noa@example.com", "role": role}
    )

    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert (body["user"]["email"], body["user"]["role"]) == ("noa@example.com", role)
    login = client.post(
        LOGIN, json={"email": "noa@example.com", "password": body["temporary_password"]}
    )
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True

    event = db_session.scalars(select(AuditEvent)).one()
    assert (event.action, event.actor_email, event.target_email) == (
        "user_added", f"{actor}@example.com", "noa@example.com"
    )
    assert event.details["temporary"] is True
    stored = [getattr(event, column.key) for column in AuditEvent.__table__.columns]
    assert all(body["temporary_password"] not in str(value) for value in stored)


@pytest.mark.parametrize(
    ("actor", "body", "status"),
    [
        ("avi", {"email": "noa@example.com", "role": "member"}, 403),
        # Already in the business, ignoring capitals.
        ("dana", {"email": "Avi@example.com", "role": "member"}, 400),
        ("dana", {"email": "not-an-email", "role": "member"}, 400),
        ("dana", {"email": "noa@example.com", "role": "leader"}, 422),
    ],
)
def test_refused_additions_create_nobody(
    client: TestClient, db_session: Session, headers, actor: str, body: dict, status: int
) -> None:
    before = user_count(db_session)

    response = client.post("/business/users", headers=headers[actor], json=body)

    assert response.status_code == status
    assert user_count(db_session) == before
    assert db_session.scalar(select(func.count()).select_from(AuditEvent)) == 0


@pytest.fixture
def people(db_session: Session, headers, auth_headers_factory, other_business) -> dict:
    """The change-2 people, plus Ori (an admin who edits all), Noa (a member) and an outsider."""
    headers = {
        **headers,
        "ori": auth_headers_factory("ori@example.com", role=ROLE_ADMIN),
        "noa": auth_headers_factory("noa@example.com"),
    }
    users = {
        name: db_session.scalar(select(User).where(User.email == f"{name}@example.com"))
        for name in headers
    }
    users["ori"].edits_all_tasks = True
    users["boss"] = User(
        email="boss@other.example", hashed_password="not-a-real-hash",
        business=other_business, role=ROLE_ADMIN, sees_all_tasks=True,
    )
    db_session.add(users["boss"])
    db_session.flush()
    return {"headers": headers, "users": users}


def reset(client: TestClient, people: dict, actor: str, target: str):
    return client.post(
        f"/business/users/{people['users'][target].id}/password-reset",
        headers=people["headers"][actor],
    )


@pytest.mark.parametrize(("actor", "target"), [("dana", "eli"), ("dana", "avi"), ("ori", "avi")])
def test_allowed_resets_give_a_temporary_password_and_end_logins(
    client: TestClient, db_session: Session, people, token_headers, actor: str, target: str
) -> None:
    user = people["users"][target]
    # A login from a minute ago; one from the same second would outlive the cut-off.
    old_login = token_headers(user.id, datetime.now(timezone.utc) - timedelta(minutes=1))

    response = reset(client, people, actor, target)

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    password = response.json()["temporary_password"]
    assert client.get("/me", headers=old_login).status_code == 401
    email = f"{target}@example.com"
    assert client.post(LOGIN, json={"email": email, "password": "password123"}).status_code == 401
    login = client.post(LOGIN, json={"email": email, "password": password})
    assert login.json()["must_change_password"] is True

    event = db_session.scalars(select(AuditEvent)).one()
    assert (event.action, event.actor_email, event.target_email, event.details) == (
        "password_reset", f"{actor}@example.com", email, {"temporary": True}
    )
    stored = [getattr(event, column.key) for column in AuditEvent.__table__.columns]
    assert all(password not in str(value) for value in stored)


@pytest.mark.parametrize(
    ("actor", "target", "status"),
    [
        ("eli", "avi", 403),   # admin who edits only own tasks
        ("ori", "eli", 403),   # admins reset only members
        ("avi", "noa", 403),   # members reset no one
        ("dana", "dana", 403), # not yourself
        ("ori", "dana", 403),  # not the leader
        ("ori", "boss", 404),  # another business: not revealed
    ],
)
def test_refused_resets_change_nothing(
    client: TestClient, db_session: Session, people, actor: str, target: str, status: int
) -> None:
    response = reset(client, people, actor, target)

    assert response.status_code == status
    assert db_session.scalar(select(func.count()).select_from(AuditEvent)) == 0
    if target != "boss":
        email = f"{target}@example.com"
        assert client.post(LOGIN, json={"email": email, "password": "password123"}).status_code == 200


def test_a_reset_uses_the_actors_current_access(
    client: TestClient, db_session: Session, people
) -> None:
    # The leader removed Ori's edit-all access a moment ago: saved in the database,
    # while this request's copy of Ori still shows the old value.
    db_session.execute(
        update(User).where(User.email == "ori@example.com").values(edits_all_tasks=False),
        execution_options={"synchronize_session": False},
    )

    response = reset(client, people, "ori", "avi")

    assert response.status_code == 403
    assert "edit all tasks" in response.json()["detail"]
