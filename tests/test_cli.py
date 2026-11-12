import getpass
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend import cli
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
    test_business: Business,
) -> None:
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
    test_business: Business,
) -> None:
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
    test_business: Business,
) -> None:
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
