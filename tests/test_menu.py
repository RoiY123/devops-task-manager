import getpass
import sys
from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.cli import main
from app.backend.models import ROLE_ADMIN, ROLE_MEMBER, Business, User


PASSWORD = "correct-horse-battery"


class FakeStdin:
    """Stands in for the keyboard; only answers whether a person is at a terminal."""

    def __init__(self, interactive: bool) -> None:
        self.interactive = interactive

    def isatty(self) -> bool:
        return self.interactive


def scripted(answers: list[str]) -> Callable[[str], str]:
    # An unexpected extra prompt raises StopIteration and fails the test.
    remaining = iter(answers)
    return lambda prompt: next(remaining)


def run_menu(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    answers: list[str],
    passwords: list[str] | None = None,
    interactive: bool = True,
) -> int:
    monkeypatch.setattr(sys, "stdin", FakeStdin(interactive))
    monkeypatch.setattr("builtins.input", scripted(answers))
    monkeypatch.setattr(getpass, "getpass", scripted(passwords or []))
    # The real CLI starts as a new process and only sees committed data.
    # This commit stays inside the test's outer transaction, which is rolled back.
    db_session.commit()
    return main(["menu"], session_factory=lambda: db_session)


def find_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def test_menu_lists_every_action_and_exits_on_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    exit_code = run_menu(monkeypatch, db_session, ["0"])

    assert exit_code == 0
    output = capsys.readouterr().out
    for label in [
        "1  Create business",
        "6  Change task visibility",
        "7  Remove user",
        "9  Delete business",
        "0  Exit",
    ]:
        assert label in output


def test_menu_adds_a_user_with_hidden_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    test_business: Business,
) -> None:
    exit_code = run_menu(
        monkeypatch,
        db_session,
        ["3", "test-business", "avi@example.com", "member", "0"],
        passwords=[PASSWORD, PASSWORD],
    )

    assert exit_code == 0
    output = capsys.readouterr()
    assert "Added member avi@example.com" in output.out
    assert PASSWORD not in output.out + output.err
    assert find_user(db_session, "avi@example.com").role == ROLE_MEMBER


def test_blank_answer_cancels_without_changes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    test_business: Business,
) -> None:
    # Blank email: no password prompt (none scripted) and no user created.
    exit_code = run_menu(monkeypatch, db_session, ["3", "test-business", "", "0"])

    assert exit_code == 0
    assert "Cancelled; nothing was changed." in capsys.readouterr().out
    assert find_user(db_session, "avi@example.com") is None


def test_error_returns_to_the_menu(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    exit_code = run_menu(
        monkeypatch,
        db_session,
        ["3", "no-such-business", "avi@example.com", "member", "0"],
    )

    assert exit_code == 0
    output = capsys.readouterr()
    assert "Error: No business with slug 'no-such-business'" in output.err
    # Shown once at the start and again after the error.
    assert output.out.count("Task Manager operator menu") == 2


def test_list_users_treats_blank_business_as_all(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")

    exit_code = run_menu(monkeypatch, db_session, ["2", "", "0"])

    assert exit_code == 0
    assert "test-business  (עסק בדיקות)  user" in capsys.readouterr().out


def test_menu_removal_uses_the_typed_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")

    exit_code = run_menu(
        monkeypatch,
        db_session,
        ["7", "test-business", "avi@example.com", "avi@example.com", "0"],
    )

    assert exit_code == 0
    assert "Removed avi@example.com" in capsys.readouterr().out
    assert find_user(db_session, "avi@example.com") is None


# What Backspace on a Hebrew letter leaves behind: half of the letter's UTF-8 bytes.
LEFTOVER_BYTE = chr(0xDCD7)


def test_unreadable_answer_reports_error_and_returns_to_menu(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    test_business: Business,
) -> None:
    # The error comes at the email answer, so the role question is never asked
    # and the next answer ("0") is read by the menu.
    exit_code = run_menu(
        monkeypatch,
        db_session,
        ["3", "test-business", f"{LEFTOVER_BYTE}avi@example.com", "0"],
    )

    assert exit_code == 0
    output = capsys.readouterr()
    assert "could not be read" in output.err
    assert output.out.count("Task Manager operator menu") == 2
    assert find_user(db_session, "avi@example.com") is None


def test_unreadable_password_in_menu_returns_to_menu(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    test_business: Business,
) -> None:
    # The real getpass decodes strictly: a leftover byte raises while reading.
    def leftover_byte(prompt: str) -> str:
        raise UnicodeDecodeError("utf-8", b"\xd7", 0, 1, "invalid continuation byte")

    monkeypatch.setattr(sys, "stdin", FakeStdin(True))
    monkeypatch.setattr(
        "builtins.input",
        scripted(["3", "test-business", "avi@example.com", "member", "0"]),
    )
    monkeypatch.setattr(getpass, "getpass", leftover_byte)
    db_session.commit()

    exit_code = main(["menu"], session_factory=lambda: db_session)

    assert exit_code == 0
    output = capsys.readouterr()
    assert "could not be read" in output.err
    assert output.out.count("Task Manager operator menu") == 2
    assert find_user(db_session, "avi@example.com") is None


# Entries not exercised above, so a menu field that does not match its
# handler's arguments fails here instead of in production.
def test_menu_creates_a_business(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    exit_code = run_menu(
        monkeypatch,
        db_session,
        ["1", "אינסטלציה כהן", "cohen-plumbing", "dana@cohen.example", "0"],
        passwords=[PASSWORD, PASSWORD],
    )

    assert exit_code == 0
    assert "Created business 'cohen-plumbing'" in capsys.readouterr().out
    assert find_user(db_session, "dana@cohen.example").business.slug == "cohen-plumbing"


def test_menu_resets_a_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com", password="old-password-123")

    exit_code = run_menu(
        monkeypatch,
        db_session,
        ["4", "test-business", "avi@example.com", "0"],
        passwords=[PASSWORD, PASSWORD],
    )

    assert exit_code == 0
    assert "Password reset for avi@example.com" in capsys.readouterr().out


def test_menu_changes_a_role(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")

    exit_code = run_menu(
        monkeypatch,
        db_session,
        ["5", "test-business", "avi@example.com", "admin", "0"],
    )

    assert exit_code == 0
    assert "from member to admin" in capsys.readouterr().out
    assert find_user(db_session, "avi@example.com").role == "admin"


def test_menu_renames_and_deletes_a_business(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    db_session.add(Business(name="עסק ריק", slug="empty-business"))
    db_session.flush()

    exit_code = run_menu(
        monkeypatch,
        db_session,
        [
            "8", "empty-business", "שם חדש",
            "9", "empty-business", "empty-business",
            "0",
        ],
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "from 'עסק ריק' to 'שם חדש'" in output
    assert "Deleted business 'empty-business'." in output
    assert db_session.scalar(
        select(Business).where(Business.slug == "empty-business")
    ) is None


def test_unknown_choice_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    exit_code = run_menu(monkeypatch, db_session, ["99", "0"])

    assert exit_code == 0
    assert "Unknown choice '99'." in capsys.readouterr().out


def test_menu_refuses_without_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    # No scripted answers: showing the menu would fail the test.
    exit_code = run_menu(monkeypatch, db_session, [], interactive=False)

    assert exit_code == 1
    assert "interactively" in capsys.readouterr().err


def test_ctrl_c_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    def interrupt(prompt: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(sys, "stdin", FakeStdin(True))
    monkeypatch.setattr("builtins.input", interrupt)

    exit_code = main(["menu"], session_factory=lambda: db_session)

    assert exit_code == 1
    assert "Exited; an unfinished action was not saved." in capsys.readouterr().out


def test_menu_changes_task_visibility(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com")

    exit_code = run_menu(
        monkeypatch,
        db_session,
        ["6", "test-business", "avi@example.com", "all", "0"],
    )

    assert exit_code == 0
    assert "avi@example.com now sees all tasks." in capsys.readouterr().out
    assert find_user(db_session, "avi@example.com").sees_all_tasks is True


def test_menu_rejects_an_unknown_visibility(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")

    run_menu(
        monkeypatch,
        db_session,
        ["6", "test-business", "avi@example.com", "some", "0"],
    )

    assert "Visibility must be 'all' or 'own'" in capsys.readouterr().err
