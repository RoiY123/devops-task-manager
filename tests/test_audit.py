import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.accounts import (
    OperatorError,
    add_user,
    end_sessions,
    grant_task_edit,
    grant_task_view,
    remove_user,
    reset_password,
    revoke_task_edit,
    revoke_task_view,
    set_role,
    set_task_editing,
    set_task_visibility,
    transfer_leadership,
)
from app.backend.audit import list_audit_events
from app.backend.businesses import delete_business
from app.backend.models import ROLE_ADMIN, AuditEvent, User
from app.backend.onboarding import create_business_with_admin


SLUG = "test-business"
PASSWORD = "correct-horse-battery"


def events(db: Session, slug: str = SLUG) -> list[tuple]:
    """(actor, action, target, details), oldest first, for readable comparisons."""
    rows = db.scalars(
        select(AuditEvent).where(AuditEvent.business_slug == slug).order_by(AuditEvent.id)
    )
    return [
        (row.actor_email or row.actor_kind, row.action, row.target_email, row.details)
        for row in rows
    ]


def event_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AuditEvent))


def user_id(db: Session, email: str) -> int:
    return db.scalar(select(User.id).where(User.email == email))


def test_operator_changes_are_recorded_with_their_details(
    db_session: Session,
    user_factory,
) -> None:
    # Created directly, so the leader's creation itself is not an event here.
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user = {"business_slug": SLUG}
    pair = {**user, "viewer_email": "noa@example.com", "owner_email": "avi@example.com"}

    add_user(db_session, **user, email="avi@example.com", role="member", password=PASSWORD)
    add_user(db_session, **user, email="noa@example.com", role="member", password=PASSWORD)
    set_role(db_session, **user, email="avi@example.com", role=ROLE_ADMIN)
    set_task_visibility(db_session, **user, email="noa@example.com", sees_all=True)
    set_task_editing(db_session, **user, email="noa@example.com", edits_all=True)
    set_task_visibility(db_session, **user, email="noa@example.com", sees_all=False)
    grant_task_view(db_session, **pair)
    grant_task_edit(db_session, **pair)
    revoke_task_edit(db_session, **pair)
    revoke_task_view(db_session, **pair)
    transfer_leadership(db_session, **user, email="avi@example.com")
    reset_password(db_session, **user, email="noa@example.com", password=PASSWORD + "!")
    end_sessions(db_session, **user, email="noa@example.com")
    remove_user(db_session, **user, email="noa@example.com")

    avi = {"owner_id": user_id(db_session, "avi@example.com"), "owner_email": "avi@example.com"}
    assert events(db_session) == [
        ("operator", "user_added", "avi@example.com", {"role": "member", "leader": False}),
        ("operator", "user_added", "noa@example.com", {"role": "member", "leader": False}),
        ("operator", "role_changed", "avi@example.com", {"from": "member", "to": "admin"}),
        ("operator", "task_visibility_changed", "noa@example.com", {"to": "all", "grants_removed": 0}),
        ("operator", "task_editing_changed", "noa@example.com", {"to": "all", "grants_changed": 0}),
        ("operator", "task_visibility_changed", "noa@example.com", {"to": "own", "grants_removed": 0}),
        ("operator", "view_granted", "noa@example.com", avi),
        ("operator", "edit_granted", "noa@example.com", avi),
        ("operator", "edit_revoked", "noa@example.com", avi),
        ("operator", "view_revoked", "noa@example.com", avi),
        (
            "operator", "leadership_transferred", "avi@example.com",
            {"previous_leader_email": "dana@example.com"},
        ),
        ("operator", "password_reset", "noa@example.com", {}),
        ("operator", "sessions_ended", "noa@example.com", {}),
        ("operator", "user_removed", "noa@example.com", {"tasks_deleted": 0}),
    ]


def test_api_changes_record_the_logged_in_user(
    client: TestClient,
    db_session: Session,
    auth_headers_factory,
) -> None:
    dana = auth_headers_factory("dana@example.com", role=ROLE_ADMIN)
    auth_headers_factory("avi@example.com")

    response = client.put(
        f"/business/users/{user_id(db_session, 'avi@example.com')}/role",
        headers=dana,
        json={"role": "admin"},
    )

    assert response.status_code == 200
    event = db_session.scalars(select(AuditEvent)).one()
    assert (event.actor_kind, event.actor_user_id, event.actor_email) == (
        "user",
        user_id(db_session, "dana@example.com"),
        "dana@example.com",
    )
    assert (event.action, event.target_email) == ("role_changed", "avi@example.com")


def test_no_ops_and_refusals_record_nothing(
    client: TestClient,
    db_session: Session,
    auth_headers_factory,
) -> None:
    dana = auth_headers_factory("dana@example.com", role=ROLE_ADMIN)
    auth_headers_factory("avi@example.com")
    noa = auth_headers_factory("noa@example.com")
    pair = {"business_slug": SLUG, "viewer_email": "noa@example.com", "owner_email": "avi@example.com"}
    grant_task_view(db_session, **pair)
    before = event_count(db_session)

    # Changes that change nothing.
    grant_task_view(db_session, **pair)
    set_role(db_session, business_slug=SLUG, email="avi@example.com", role="member")
    set_task_visibility(db_session, business_slug=SLUG, email="avi@example.com", sees_all=False)
    set_task_editing(db_session, business_slug=SLUG, email="avi@example.com", edits_all=False)
    # Refusals: by permission (403) and by a data rule (400).
    avi_url = f"/business/users/{user_id(db_session, 'avi@example.com')}"
    assert client.put(f"{avi_url}/task-visibility", headers=noa, json={"level": "all"}).status_code == 403
    assert client.put(f"{avi_url}/task-editing", headers=dana, json={"level": "all"}).status_code == 400

    assert event_count(db_session) == before


def test_a_change_that_fails_leaves_no_record(
    db_session: Session,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com")
    # Saved, so the failed add below cannot roll these users back as well.
    db_session.commit()
    # The race where the email is taken while the operator types the password:
    # the check passes, then the database's unique index refuses the insert.
    monkeypatch.setattr("app.backend.accounts.ensure_email_is_free", lambda *args: None)

    with pytest.raises(OperatorError, match="was taken while adding the user"):
        add_user(
            db_session,
            business_slug=SLUG,
            email="avi@example.com",
            role="member",
            password=PASSWORD,
        )

    assert event_count(db_session) == 0
    assert db_session.scalar(
        select(func.count()).select_from(User).where(User.email == "avi@example.com")
    ) == 1


def test_password_reset_never_records_the_password(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")
    secret = "a-new-secret-password-123"

    reset_password(db_session, business_slug=SLUG, email="avi@example.com", password=secret)

    event = db_session.scalars(select(AuditEvent)).one()
    assert event.details == {}
    stored = [getattr(event, column.key) for column in AuditEvent.__table__.columns]
    assert all(secret not in str(value) for value in stored)


def test_history_outlives_removed_users_and_a_deleted_business(db_session: Session) -> None:
    slug = "gone-business"
    create_business_with_admin(
        db_session,
        name="עסק שנמחק",
        slug=slug,
        admin_email="dana@gone.example",
        admin_password=PASSWORD,
    )
    add_user(
        db_session, business_slug=slug, email="avi@gone.example", role="member", password=PASSWORD
    )
    remove_user(db_session, business_slug=slug, email="avi@gone.example")
    remove_user(db_session, business_slug=slug, email="dana@gone.example")
    delete_business(db_session, slug=slug)

    assert [event.action for event in reversed(list_audit_events(db_session, slug, 50))] == [
        "business_created",
        "user_added",
        "user_removed",
        "user_removed",
        "business_deleted",
    ]
