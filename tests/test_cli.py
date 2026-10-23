import getpass
import sys

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.cli import main
from app.backend.models import ROLE_ADMIN, Business, User


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
) -> int:
    # Each getpass call receives the next scripted answer;
    # an unexpected extra call raises StopIteration and fails the test.
    answers = iter(passwords)
    monkeypatch.setattr(sys, "stdin", FakeStdin(interactive))
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(answers))
    return main(args, session_factory=lambda: db_session)


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


def test_rejected_slug_reports_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    before = business_count(db_session)
    args = [*ARGS[:3], "--slug", "Cohen Plumbing", *ARGS[5:]]

    exit_code = run_cli(monkeypatch, db_session, args, [PASSWORD, PASSWORD])

    assert exit_code == 1
    assert "Error: Slug 'Cohen Plumbing' is invalid" in capsys.readouterr().err
    assert business_count(db_session) == before
