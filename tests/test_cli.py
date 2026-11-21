import getpass
import re
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend import cli
from app.backend.accounts import add_user, set_role
from app.backend.cli import main
from app.backend.models import ROLE_ADMIN, ROLE_MEMBER, AuditEvent, Business, Task, User


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
        "/businesses/test-business/login", json={"email": email, "password": password}
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
    assert "with leader dana@cohen.example" in output.out
    # Command output may end up in terminal scrollback or session logs.
    assert PASSWORD not in output.out + output.err

    admin = db_session.scalar(
        select(User).where(User.email == "dana@cohen.example")
    )
    assert admin.role == ROLE_ADMIN
    assert admin.business.slug == "cohen-plumbing"
    assert admin.is_leader


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


def test_email_taken_in_the_business_is_reported_before_asking_for_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")

    # No scripted passwords: the email must be rejected before any prompt.
    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("add-user", "Avi@Example.com", "--role", "member"),
        [],
    )

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
    user_factory,
) -> None:
    # A leader first: the first user of an empty business must be an admin.
    user_factory("dana@example.com", role=ROLE_ADMIN)

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
    db_session.add(Task(title="Avi 1", owner=avi, business_id=avi.business_id))
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
    assert "is the leader of 'test-business'" in capsys.readouterr().err


# What Backspace on a Hebrew letter leaves behind: half of the letter's UTF-8 bytes.
LEFTOVER_BYTE = chr(0xDCD7)


def test_unreadable_argument_is_rejected_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    test_business: Business,
) -> None:
    business_id = test_business.id

    exit_code = run_cli(
        monkeypatch,
        db_session,
        ["rename-business", "--slug", "test-business", "--name", f"שם{LEFTOVER_BYTE}"],
        [],
        interactive=False,
    )

    assert exit_code == 1
    assert "could not be read" in capsys.readouterr().err
    assert db_session.get(Business, business_id).name == "עסק בדיקות"


def test_unreadable_password_is_rejected_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)

    # The real getpass decodes strictly: a leftover byte raises while reading
    # instead of being returned, which is what this stand-in reproduces.
    def leftover_byte(prompt: str) -> str:
        raise UnicodeDecodeError("utf-8", b"\xd7", 0, 1, "invalid continuation byte")

    monkeypatch.setattr(sys, "stdin", FakeStdin(True))
    monkeypatch.setattr(getpass, "getpass", leftover_byte)
    db_session.commit()

    exit_code = main(
        user_args("add-user", "avi@example.com", "--role", "member"),
        session_factory=lambda: db_session,
    )

    assert exit_code == 1
    assert "could not be read" in capsys.readouterr().err
    assert db_session.scalar(
        select(User).where(User.email == "avi@example.com")
    ) is None


def test_unreadable_confirmation_is_reported_as_unreadable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    avi_id = user_factory("avi@example.com").id

    # The right email after a Backspace on a Hebrew letter: not a mismatch.
    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("remove-user", "avi@example.com"),
        [],
        confirmations=[f"{LEFTOVER_BYTE}avi@example.com"],
    )

    assert exit_code == 1
    assert "could not be read" in capsys.readouterr().err
    assert db_session.get(User, avi_id) is not None


def test_ctrl_c_at_a_prompt_cancels_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)

    def interrupt(prompt: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(sys, "stdin", FakeStdin(True))
    monkeypatch.setattr(getpass, "getpass", interrupt)
    db_session.commit()

    exit_code = main(
        user_args("add-user", "avi@example.com", "--role", "member"),
        session_factory=lambda: db_session,
    )

    assert exit_code == 130
    assert "Cancelled; nothing was saved." in capsys.readouterr().err
    assert db_session.scalar(
        select(User).where(User.email == "avi@example.com")
    ) is None


class FakeTermiosWithoutName:
    """Records terminal-setting changes; stands in for termios on any OS.

    Like Python 3.12's termios, it does not export the IUTF8 name.
    """

    TCSANOW = 0
    error = OSError

    def __init__(self) -> None:
        self.current = [0x0100, 0, 0, 0, 0, 0, []]
        self.history: list[int] = []

    def tcgetattr(self, fd: int) -> list:
        return list(self.current)

    def tcsetattr(self, fd: int, when: int, attributes: list) -> None:
        self.current = list(attributes)
        self.history.append(attributes[0])


class FakeTermios(FakeTermiosWithoutName):
    """A termios that exports IUTF8, as newer Python versions may."""

    IUTF8 = 0x4000


class FakeTerminal(FakeStdin):
    def fileno(self) -> int:
        return 0


@pytest.fixture
def fake_termios(monkeypatch: pytest.MonkeyPatch) -> FakeTermios:
    fake = FakeTermios()
    monkeypatch.setattr(cli, "termios", fake)
    return fake


@pytest.mark.parametrize(
    ("platform", "expected_history"),
    [
        # The container: Linux with Python 3.12, so the fallback value is used.
        ("linux", [0x0100 | cli.LINUX_IUTF8, 0x0100]),
        # Elsewhere the Linux value may be wrong, so nothing is changed.
        ("darwin", []),
    ],
)
def test_utf8_line_editing_falls_back_to_the_linux_value(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    test_business: Business,
    platform: str,
    expected_history: list[int],
) -> None:
    fake = FakeTermiosWithoutName()
    monkeypatch.setattr(cli, "termios", fake)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "stdin", FakeTerminal(True))

    main(["list-users"], session_factory=lambda: db_session)

    assert fake.history == expected_history


def test_utf8_line_editing_is_on_during_a_command_and_restored_after(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    fake_termios: FakeTermios,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    seen_during_command = []
    monkeypatch.setattr(sys, "stdin", FakeTerminal(True))
    monkeypatch.setattr(
        getpass,
        "getpass",
        lambda prompt: seen_during_command.append(fake_termios.current[0]) or PASSWORD,
    )
    db_session.commit()

    exit_code = main(
        user_args("add-user", "avi@example.com", "--role", "member"),
        session_factory=lambda: db_session,
    )

    assert exit_code == 0
    # On while the password was typed, and the original flags afterwards.
    assert all(flags & FakeTermios.IUTF8 for flags in seen_during_command)
    assert fake_termios.current[0] == 0x0100


def test_utf8_line_editing_is_restored_after_an_error(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    fake_termios: FakeTermios,
) -> None:
    monkeypatch.setattr(sys, "stdin", FakeTerminal(True))

    exit_code = main(
        ["rename-business", "--slug", "no-such", "--name", "x"],
        session_factory=lambda: db_session,
    )

    assert exit_code == 1
    assert fake_termios.history == [0x0100 | FakeTermios.IUTF8, 0x0100]


def test_utf8_line_editing_is_not_touched_without_a_terminal(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    fake_termios: FakeTermios,
    test_business: Business,
) -> None:
    monkeypatch.setattr(sys, "stdin", FakeTerminal(False))

    main(["list-users"], session_factory=lambda: db_session)

    assert fake_termios.history == []


def add_empty_business(db: Session) -> int:
    business = Business(name="עסק ריק", slug="empty-business")
    db.add(business)
    db.flush()
    return business.id


def test_rename_business_needs_no_terminal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    test_business: Business,
) -> None:
    business_id = test_business.id

    exit_code = run_cli(
        monkeypatch,
        db_session,
        ["rename-business", "--slug", "test-business", "--name", "שם חדש"],
        [],
        interactive=False,
    )

    assert exit_code == 0
    assert "from 'עסק בדיקות' to 'שם חדש'" in capsys.readouterr().out
    renamed = db_session.get(Business, business_id)
    assert (renamed.slug, renamed.name) == ("test-business", "שם חדש")


def test_delete_business_after_typed_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    business_id = add_empty_business(db_session)

    exit_code = run_cli(
        monkeypatch,
        db_session,
        ["delete-business", "--slug", "empty-business"],
        [],
        confirmations=["empty-business"],
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "permanently deletes business 'empty-business' (עסק ריק)" in output
    assert "Deleted business 'empty-business'." in output
    assert db_session.get(Business, business_id) is None


def test_delete_business_with_wrong_confirmation_deletes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    business_id = add_empty_business(db_session)

    exit_code = run_cli(
        monkeypatch,
        db_session,
        ["delete-business", "--slug", "empty-business"],
        [],
        confirmations=["empty-busines"],
    )

    assert exit_code == 1
    assert "nothing was deleted" in capsys.readouterr().err
    assert db_session.get(Business, business_id) is not None


def test_business_with_users_is_refused_before_asking_for_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")

    # No scripted confirmation: asking for one would fail the test.
    exit_code = run_cli(
        monkeypatch, db_session, ["delete-business", "--slug", "test-business"], []
    )

    assert exit_code == 1
    assert "has 1 users; remove them first" in capsys.readouterr().err


def test_delete_business_refuses_without_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    business_id = add_empty_business(db_session)

    exit_code = run_cli(
        monkeypatch,
        db_session,
        ["delete-business", "--slug", "empty-business"],
        [],
        interactive=False,
    )

    assert exit_code == 1
    assert "interactively" in capsys.readouterr().err
    assert db_session.get(Business, business_id) is not None


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


def test_set_task_visibility_reports_the_change(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com")

    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("set-task-visibility", "avi@example.com", "--all"),
        [],
        interactive=False,
    )

    assert exit_code == 0
    assert "avi@example.com now sees all tasks." in capsys.readouterr().out


def test_set_task_visibility_refuses_an_admin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("eli@example.com", role=ROLE_ADMIN)

    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("set-task-visibility", "eli@example.com", "--own"),
        [],
        interactive=False,
    )

    assert exit_code == 1
    assert "admins always see all tasks" in capsys.readouterr().err


def test_set_task_editing_reports_the_change_and_needs_seeing_all(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("eli@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com")

    run_cli(
        monkeypatch,
        db_session,
        user_args("set-task-editing", "eli@example.com", "--all"),
        [],
        interactive=False,
    )
    assert "eli@example.com now edits all tasks." in capsys.readouterr().out

    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("set-task-editing", "avi@example.com", "--all"),
        [],
        interactive=False,
    )
    assert exit_code == 1
    assert "set visibility to all first" in capsys.readouterr().err


def test_list_users_and_set_role_show_task_visibility(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("eli@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com")

    run_cli(
        monkeypatch,
        db_session,
        ["list-users", "--business", "test-business"],
        [],
        interactive=False,
    )
    listing = capsys.readouterr().out
    assert "dana@example.com  leader  sees all  edits all" in listing
    assert "eli@example.com  admin  sees all  edits own" in listing
    assert "avi@example.com  member  sees own  edits own" in listing

    run_cli(
        monkeypatch,
        db_session,
        user_args("set-role", "avi@example.com", "--role", "admin"),
        [],
        interactive=False,
    )
    assert (
        "from member to admin; now sees all tasks and edits own tasks."
        in capsys.readouterr().out
    )


def grant_args(command: str, viewer: str, owner: str) -> list[str]:
    return [
        command, "--business", "test-business", "--viewer", viewer, "--owner", owner
    ]


def test_grant_task_view_reports_new_and_repeated_grants(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")
    user_factory("noa@example.com")
    args = grant_args("grant-task-view", "noa@example.com", "avi@example.com")

    run_cli(monkeypatch, db_session, args, [], interactive=False)
    assert (
        "noa@example.com now sees the tasks of avi@example.com (view only)."
        in capsys.readouterr().out
    )

    run_cli(monkeypatch, db_session, args, [], interactive=False)
    assert (
        "already sees the tasks of avi@example.com; nothing changed."
        in capsys.readouterr().out
    )


def test_view_grant_is_refused_for_a_viewer_who_sees_all_tasks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com")

    exit_code = run_cli(
        monkeypatch,
        db_session,
        grant_args("grant-task-view", "dana@example.com", "avi@example.com"),
        [],
        interactive=False,
    )

    assert exit_code == 1
    assert "dana@example.com already sees all tasks" in capsys.readouterr().err


def test_grant_and_revoke_task_edit_report_the_change(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("eli@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com")

    for command, expected in [
        ("grant-task-edit", "eli@example.com can now change the tasks of avi@example.com."),
        ("grant-task-edit", "can already change the tasks of avi@example.com; nothing changed."),
        ("revoke-task-edit", "eli@example.com can no longer change the tasks of avi@example.com."),
        ("revoke-task-edit", "had no edit grant for the tasks of avi@example.com; nothing changed."),
    ]:
        run_cli(
            monkeypatch,
            db_session,
            grant_args(command, "eli@example.com", "avi@example.com"),
            [],
            interactive=False,
        )
        assert expected in capsys.readouterr().out


def test_revoke_and_list_report_when_there_is_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")
    user_factory("noa@example.com")

    run_cli(
        monkeypatch,
        db_session,
        ["list-task-grants", "--business", "test-business"],
        [],
        interactive=False,
    )
    assert "No task grants in business 'test-business'." in capsys.readouterr().out

    run_cli(
        monkeypatch,
        db_session,
        grant_args("revoke-task-view", "noa@example.com", "avi@example.com"),
        [],
        interactive=False,
    )
    assert (
        "had no grant for the tasks of avi@example.com; nothing changed."
        in capsys.readouterr().out
    )


def test_grant_to_the_same_user_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")

    exit_code = run_cli(
        monkeypatch,
        db_session,
        grant_args("grant-task-view", "avi@example.com", "avi@example.com"),
        [],
        interactive=False,
    )

    assert exit_code == 1
    assert "always sees their own tasks" in capsys.readouterr().err


def test_transfer_leadership_names_both_users(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com", role=ROLE_ADMIN)

    exit_code = run_cli(
        monkeypatch,
        db_session,
        ["transfer-leadership", "--business", "test-business", "--to", "avi@example.com"],
        [],
        interactive=False,
    )

    assert exit_code == 0
    assert (
        "avi@example.com is now the leader of 'test-business'; "
        "dana@example.com remains an admin."
    ) in capsys.readouterr().out


def test_first_admin_of_an_empty_business_is_added_as_its_leader(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    test_business: Business,
) -> None:
    exit_code = run_cli(
        monkeypatch,
        db_session,
        user_args("add-user", "dana@example.com", "--role", "admin"),
        [PASSWORD, PASSWORD],
    )

    assert exit_code == 0
    assert "to business 'test-business' as its leader." in capsys.readouterr().out


def test_list_users_warns_about_users_without_a_leader(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    # Created directly, as an image from before the leader migration could.
    user_factory("avi@example.com")

    run_cli(
        monkeypatch,
        db_session,
        ["list-users", "--business", "test-business"],
        [],
        interactive=False,
    )

    assert (
        "Warning: business 'test-business' has users but no leader; "
        "run transfer-leadership."
    ) in capsys.readouterr().out


def audit_log(monkeypatch, db_session, *extra: str) -> int:
    return run_cli(
        monkeypatch,
        db_session,
        ["audit-log", "--business", "test-business", *extra],
        [],
        interactive=False,
    )


def test_audit_log_shows_the_latest_events_oldest_to_newest_in_utc(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    add_user(
        db_session,
        business_slug="test-business",
        email="avi@example.com",
        role=ROLE_MEMBER,
        password=PASSWORD,
    )
    set_role(db_session, business_slug="test-business", email="avi@example.com", role=ROLE_ADMIN)

    assert audit_log(monkeypatch, db_session) == 0

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert all(re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC  ", line) for line in lines)
    # Like tail: the most recent event is the last line.
    assert lines[0].endswith("operator  user_added  avi@example.com  leader=False role=member")
    assert lines[1].endswith("operator  role_changed  avi@example.com  from=member to=admin")


@pytest.mark.parametrize("limit", ["0", "1001"])
def test_audit_log_refuses_a_limit_out_of_range(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    limit: str,
) -> None:
    assert audit_log(monkeypatch, db_session, "--limit", limit) == 1
    assert "from 1 to 1000" in capsys.readouterr().err


def test_audit_log_limit_and_empty_log(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    audit_log(monkeypatch, db_session)
    assert "No audit events for business 'test-business'." in capsys.readouterr().out

    user_factory("dana@example.com", role=ROLE_ADMIN)
    for email in ["avi@example.com", "noa@example.com"]:
        add_user(
            db_session,
            business_slug="test-business",
            email=email,
            role=ROLE_MEMBER,
            password=PASSWORD,
        )

    audit_log(monkeypatch, db_session, "--limit", "1")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert "noa@example.com" in lines[0]


def test_audit_log_notes_a_slug_used_by_two_businesses(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    # A deleted business's slug, reused by a new business.
    for business_id in (101, 202):
        db_session.add(
            AuditEvent(
                business_id=business_id,
                business_slug="test-business",
                actor_kind="operator",
                action="business_created",
            )
        )
    db_session.flush()

    audit_log(monkeypatch, db_session)

    assert (
        "belong to more than one business with this slug (ids 101, 202)"
        in capsys.readouterr().out
    )
