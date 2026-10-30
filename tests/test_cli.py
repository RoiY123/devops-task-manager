import getpass
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.cli import main
from app.backend.models import ROLE_ADMIN, ROLE_MEMBER, Business, Task, User


ARGS = [
    "create-business",
    "--name", "אינסטלציה כהן",
    "--slug", "cohen-plumbing",
    "--admin-email", "dana@cohen.example",
]
PASSWORD = "correct-horse-battery"


class FakeStdin:
    """Stands in for the keyboard; only answers whether a person is at a terminal."""

    def __init__(self, interactive: bool) -> None:
        self.interactive = interactive

    def isatty(self) -> bool:
        return self.interactive


def run_cli(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    args: list[str],
    passwords: list[str],
    interactive: bool = True,
    confirmations: list[str] | None = None,
) -> int:
    # Each getpass or input call receives the next scripted answer;
    # an unexpected extra call raises StopIteration and fails the test.
    answers = iter(passwords)
    typed = iter(confirmations or [])
    monkeypatch.setattr(sys, "stdin", FakeStdin(interactive))
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(answers))
    monkeypatch.setattr("builtins.input", lambda prompt: next(typed))
    # The real CLI starts as a new process and only sees committed data.
    # This commit stays inside the test's outer transaction, which is rolled back.
    db_session.commit()
    return main(args, session_factory=lambda: db_session)


def user_args(command: str, email: str, *extra: str) -> list[str]:
    return [command, "--business", "test-business", "--email", email, *extra]


def login_status(client: TestClient, email: str, password: str) -> int:
    return client.post(
        "/login", json={"email": email, "password": password}
    ).status_code


def business_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Business))


def test_creates_business_and_admin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    exit_code = run_cli(monkeypatch, db_session, ARGS, [PASSWORD, PASSWORD])

    assert exit_code == 0

    output = capsys.readouterr()
    assert "cohen-plumbing" in output.out
    # Command output may end up in terminal scrollback or session logs.
    assert PASSWORD not in output.out + output.err

    admin = db_session.scalar(
        select(User).where(User.email == "dana@cohen.example")
    )
    assert admin.role == ROLE_ADMIN
    assert admin.business.slug == "cohen-plumbing"


def test_mismatched_passwords_create_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    before = business_count(db_session)

    exit_code = run_cli(
        monkeypatch, db_session, ARGS, [PASSWORD, "correct-horse-batteyr"]
    )

    assert exit_code == 1
    assert "do not match" in capsys.readouterr().err
    assert business_count(db_session) == before


def test_refuses_without_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    before = business_count(db_session)

    # No scripted passwords: if getpass were called, the test would fail.
    exit_code = run_cli(monkeypatch, db_session, ARGS, [], interactive=False)

    assert exit_code == 1
    assert "interactively" in capsys.readouterr().err
    assert business_count(db_session) == before


def test_rejected_slug_reports_error_before_asking_for_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    before = business_count(db_session)
    args = [*ARGS[:3], "--slug", "Cohen Plumbing", *ARGS[5:]]

    # No scripted passwords: the input must be rejected before any prompt.
    exit_code = run_cli(monkeypatch, db_session, args, [])

    assert exit_code == 1
    assert "Error: Slug 'Cohen Plumbing' is invalid" in capsys.readouterr().err
    assert business_count(db_session) == before


def test_taken_email_reports_error_before_asking_for_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@cohen.example")

    exit_code = run_cli(monkeypatch, db_session, ARGS, [])

    assert exit_code == 1
    assert "already registered" in capsys.readouterr().err


def test_list_users_needs_no_terminal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")

    # Read-only, so it also works through docker compose exec -T.
    exit_code = run_cli(
        monkeypatch,
        db_session,
        ["list-users", "--business", "test-business"],
        [],
        interactive=False,
    )

    assert exit_code == 0
    assert "avi@example.com  member" in capsys.readouterr().out


def test_add_user_creates_user_who_can_log_in(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    client: TestClient,
    db_session: Session,
    test_business: Business,
) -> None:
    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("add-user", "avi@example.com", "--role", "member"),
        [PASSWORD, PASSWORD],
    )

    assert exit_code == 0
    output = capsys.readouterr()
    assert "Added member avi@example.com" in output.out
    assert PASSWORD not in output.out + output.err
    assert login_status(client, "avi@example.com", PASSWORD) == 200


def test_add_user_to_unknown_business_fails_before_asking_for_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    args = ["add-user", "--business", "no-such-business",
            "--email", "avi@example.com", "--role", "member"]

    exit_code = run_cli(monkeypatch, db_session, args, [])

    assert exit_code == 1
    assert "No business with slug 'no-such-business'" in capsys.readouterr().err


def test_reset_password_changes_the_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    client: TestClient,
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com", password="old-password-123")

    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("reset-password", "avi@example.com"),
        [PASSWORD, PASSWORD],
    )

    assert exit_code == 0
    assert "stay valid until their tokens expire" in capsys.readouterr().out
    assert login_status(client, "avi@example.com", "old-password-123") == 401
    assert login_status(client, "avi@example.com", PASSWORD) == 200


def test_set_role_reports_the_change(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    avi_id = user_factory("avi@example.com").id

    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("set-role", "avi@example.com", "--role", "admin"),
        [],
        interactive=False,
    )

    assert exit_code == 0
    assert "from member to admin" in capsys.readouterr().out
    assert db_session.get(User, avi_id).role == ROLE_ADMIN


def test_remove_user_after_typed_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    avi = user_factory("avi@example.com")
    db_session.add(Task(title="Avi 1", owner=avi))
    db_session.flush()
    avi_id = avi.id

    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("remove-user", "avi@example.com"),
        [],
        confirmations=["avi@example.com"],
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "deletes avi@example.com and their 1 tasks" in output
    assert "deleted 1 tasks" in output
    assert db_session.get(User, avi_id) is None


def test_remove_user_with_wrong_confirmation_deletes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    avi = user_factory("avi@example.com")
    avi_id = avi.id

    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("remove-user", "avi@example.com"),
        [],
        confirmations=["avi@example.con"],
    )

    assert exit_code == 1
    assert "nothing was deleted" in capsys.readouterr().err
    assert db_session.get(User, avi_id).role == ROLE_MEMBER


def test_refused_removal_is_reported_before_asking_for_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com")

    # No scripted confirmation: asking for one would fail the test.
    exit_code = run_cli(
        monkeypatch, db_session, user_args("remove-user", "dana@example.com"), []
    )

    assert exit_code == 1
    assert "only admin" in capsys.readouterr().err


def test_remove_user_refuses_without_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    avi = user_factory("avi@example.com")
    avi_id = avi.id

    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("remove-user", "avi@example.com"),
        [],
        interactive=False,
    )

    assert exit_code == 1
    assert "interactively" in capsys.readouterr().err
    assert db_session.get(User, avi_id) is not None
