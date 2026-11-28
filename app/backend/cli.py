"""Operator commands, run inside the API container.

Examples:
    python -m app.backend.cli create-business \
        --name "אינסטלציה כהן" --slug cohen-plumbing \
        --admin-email dana@cohen.example
    python -m app.backend.cli list-users --business cohen-plumbing
    python -m app.backend.cli add-user \
        --business cohen-plumbing --email avi@cohen.example --role member
    python -m app.backend.cli menu
"""
import argparse
import getpass
import sys
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from datetime import timezone

from sqlalchemy.orm import Session

try:
    import termios
except ImportError:
    # Not available on Windows, where the tests may run; the CLI itself runs on Linux.
    termios = None

from app.backend.accounts import (
    ROLES,
    TEMPORARY_PASSWORD_LIFETIME,
    OperatorError,
    add_user,
    end_sessions,
    ensure_user_can_be_removed,
    find_user,
    get_business,
    grant_task_edit,
    grant_task_view,
    list_task_grants,
    list_users,
    reassign_all_tasks,
    remove_user,
    reset_password,
    revoke_task_edit,
    revoke_task_view,
    set_role,
    set_task_editing,
    set_task_visibility,
    transfer_leadership,
    validate_new_user,
)
from app.backend.audit import list_audit_events
from app.backend.businesses import (
    delete_business,
    ensure_business_is_empty,
    rename_business,
)
from app.backend.database import SessionLocal
from app.backend.models import ROLE_ADMIN
from app.backend.onboarding import create_business_with_admin, validate_new_business


def require_terminal() -> None:
    # getpass can hide typing only on an interactive terminal, and a
    # confirmation must come from a person. Refusing otherwise ensures
    # a password is never echoed or piped in, and nothing is auto-confirmed.
    if not sys.stdin.isatty():
        raise OperatorError(
            "Run this command interactively "
            "(for example, docker compose exec without -T)"
        )


# Linux's value for the IUTF8 terminal flag (include/uapi/asm-generic/termbits.h,
# used on x86 and ARM). Python 3.12's termios does not export the name.
LINUX_IUTF8 = 0o40000


def iutf8_flag() -> int | None:
    if termios is None:
        return None

    if hasattr(termios, "IUTF8"):
        return termios.IUTF8

    if sys.platform.startswith("linux"):
        return LINUX_IUTF8

    return None


@contextmanager
def utf8_line_editing() -> Generator[None, None, None]:
    # docker exec terminals leave IUTF8 off, so the terminal's line editing treats
    # each byte as a character and Backspace erases half of a Hebrew letter.
    # Turning it on for this session's terminal makes Backspace erase whole characters;
    # the previous setting is restored when the command ends.
    flag = iutf8_flag()

    if flag is None or not sys.stdin.isatty():
        yield
        return

    fd = sys.stdin.fileno()

    try:
        original = termios.tcgetattr(fd)
    except termios.error:
        yield
        return

    updated = list(original)
    updated[0] |= flag
    termios.tcsetattr(fd, termios.TCSANOW, updated)

    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, original)


UNREADABLE_TEXT = (
    "The text you typed contains characters that could not be read "
    "(for example, half of a Hebrew letter); "
    "retype it without corrections or paste it"
)


def ensure_readable(text: str) -> str:
    # Bytes that are not valid UTF-8 arrive as surrogate placeholders.
    # The safety net for when utf8_line_editing cannot apply: Backspace on a
    # Hebrew letter then erases only one of its two bytes and leaves one behind,
    # even if the final text looks English.
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise OperatorError(UNREADABLE_TEXT) from None

    return text


def read_hidden(prompt: str) -> str:
    # Unlike input(), getpass decodes strictly, so a leftover byte
    # fails while reading instead of arriving as a placeholder.
    try:
        return getpass.getpass(prompt)
    except UnicodeDecodeError:
        raise OperatorError(UNREADABLE_TEXT) from None


def read_new_password(label: str) -> str:
    require_terminal()

    password = read_hidden(f"{label}: ")
    confirmation = read_hidden(f"Repeat {label.lower()}: ")

    if password != confirmation:
        raise OperatorError("Passwords do not match; nothing was changed")

    return password


def password_is_temporary(args: argparse.Namespace) -> bool:
    # The command line has --permanent; the menu asks the question instead.
    if not hasattr(args, "must_change"):
        return not args.permanent
    answer = (args.must_change or "yes").strip().lower()
    if answer not in ("yes", "no"):
        raise OperatorError("Answer yes or no; nothing was changed")
    return answer == "yes"


PERMANENT_HELP = (
    "Set a normal password; by default it is temporary and must be changed "
    f"within {TEMPORARY_PASSWORD_LIFETIME.days} days."
)


def password_note(temporary: bool) -> str:
    if temporary:
        return (
            " The password is temporary: they must change it within "
            f"{TEMPORARY_PASSWORD_LIFETIME.days} days."
        )
    return " The password is permanent."


def end_read_transaction(db: Session) -> None:
    # The checks opened a transaction; holding it while the operator types
    # would make a deploy's migration wait on its table locks.
    db.rollback()


def create_business(db: Session, args: argparse.Namespace) -> str:
    temporary = password_is_temporary(args)
    validate_new_business(
        db, name=args.name, slug=args.slug, admin_email=args.admin_email
    )
    end_read_transaction(db)

    password = read_new_password("Admin password")
    result = create_business_with_admin(
        db,
        name=args.name,
        slug=args.slug,
        admin_email=args.admin_email,
        admin_password=password,
        temporary=temporary,
    )

    return (
        f"Created business {result.slug!r} (id {result.business_id}) "
        f"with leader {result.admin_email} (user id {result.admin_user_id})."
        + password_note(temporary)
    )


def visibility_text(sees_all: bool) -> str:
    return "sees all tasks" if sees_all else "sees own tasks"


def list_users_command(db: Session, args: argparse.Namespace) -> str:
    rows = list_users(db, args.business)

    if not rows:
        return "No businesses."

    lines = [
        f"{row.business_slug}  ({row.business_name})  "
        + (
            f"user {row.user_id}  {row.email}  "
            f"{'leader' if row.is_leader else row.role}  "
            f"sees {row.view_level}  edits {row.edit_level}"
            if row.user_id is not None
            else "no users"
        )
        for row in rows
    ]

    # Possible only after an older image created or changed the business.
    with_users = {row.business_slug for row in rows if row.user_id is not None}
    with_leader = {row.business_slug for row in rows if row.is_leader}
    lines += [
        f"Warning: business {slug!r} has users but no leader; run transfer-leadership."
        for slug in sorted(with_users - with_leader)
    ]

    return "\n".join(lines)


def add_user_command(db: Session, args: argparse.Namespace) -> str:
    temporary = password_is_temporary(args)
    validate_new_user(
        db, business_slug=args.business, email=args.email, role=args.role
    )
    end_read_transaction(db)

    password = read_new_password("Password")
    user = add_user(
        db,
        business_slug=args.business,
        email=args.email,
        role=args.role,
        password=password,
        temporary=temporary,
    )

    return (
        f"Added {user.role} {user.email} (user id {user.id}) "
        f"to business {args.business.strip()!r}"
        + (" as its leader." if user.is_leader else ".")
        + password_note(temporary)
    )


def reset_password_command(db: Session, args: argparse.Namespace) -> str:
    temporary = password_is_temporary(args)
    user = find_user(db, business_slug=args.business, email=args.email)
    email = user.email
    end_read_transaction(db)

    password = read_new_password("New password")
    reset_password(
        db,
        business_slug=args.business,
        email=args.email,
        password=password,
        temporary=temporary,
    )

    return (
        f"Password reset for {email}. "
        f"Their existing logins were ended; they must log in with the new password."
        + password_note(temporary)
    )


def end_sessions_command(db: Session, args: argparse.Namespace) -> str:
    user = end_sessions(db, business_slug=args.business, email=args.email)

    return (
        f"Ended every login of {user.email}; they must log in again. "
        f"Their password is unchanged."
    )


def set_role_command(db: Session, args: argparse.Namespace) -> str:
    previous = set_role(
        db, business_slug=args.business, email=args.email, role=args.role
    )

    if previous == args.role:
        return f"{args.email.strip()} is already {args.role}; nothing changed."

    return (
        f"Changed {args.email.strip()} from {previous} to {args.role}; "
        f"now {visibility_text(args.role == ROLE_ADMIN)} and edits own tasks."
    )


def remove_user_command(db: Session, args: argparse.Namespace) -> str:
    user = find_user(db, business_slug=args.business, email=args.email)
    # Checked before asking, so the operator never confirms a refused removal.
    ensure_user_can_be_removed(db, user)
    email = user.email
    task_count = len(user.tasks)
    end_read_transaction(db)

    require_terminal()
    print(f"This permanently deletes {email} and their {task_count} tasks.")
    if ensure_readable(input("Type the email again to confirm: ")).strip() != email:
        raise OperatorError("Confirmation did not match; nothing was deleted")

    deleted_tasks = remove_user(db, business_slug=args.business, email=email)

    return (
        f"Removed {email} from business {args.business.strip()!r} "
        f"and deleted {deleted_tasks} tasks."
    )


def tasks_text(count: int) -> str:
    return f"{count} task" if count == 1 else f"{count} tasks"


def reassign_tasks_command(db: Session, args: argparse.Namespace) -> str:
    source = find_user(db, business_slug=args.business, email=args.from_email)
    receiver = find_user(db, business_slug=args.business, email=args.to)
    if source.id == receiver.id:
        raise OperatorError(f"{source.email} already owns these tasks; choose another user")
    task_count = len(source.tasks)
    source_email, receiver_email = source.email, receiver.email
    end_read_transaction(db)

    if task_count == 0:
        return f"{source_email} has no tasks; nothing was moved."

    require_terminal()
    print(
        f"This moves {tasks_text(task_count)} of {source_email} to {receiver_email}.\n"
        f"{receiver_email}'s own tasks stay theirs, so moving back later needs "
        f"the task ids from the audit log."
    )
    confirmation = ensure_readable(input("Type the receiving email again to confirm: "))
    if confirmation.strip() != receiver_email:
        raise OperatorError("Confirmation did not match; nothing was moved")

    result = reassign_all_tasks(
        db, business_slug=args.business, from_email=source_email, to_email=receiver_email
    )
    moved = tasks_text(result.tasks_moved)
    return f"Moved {moved} from {source_email} to {receiver_email}." + (
        f"\n{result.people_losing_access} people who saw or changed them "
        f"through grants no longer can."
        if result.people_losing_access
        else ""
    )


def set_task_visibility_command(db: Session, args: argparse.Namespace) -> str:
    if args.visibility not in ("all", "own"):
        raise OperatorError("Visibility must be 'all' or 'own'")

    sees_all = args.visibility == "all"
    set_task_visibility(
        db, business_slug=args.business, email=args.email, sees_all=sees_all
    )

    return f"{args.email.strip()} now {visibility_text(sees_all)}."


def set_task_editing_command(db: Session, args: argparse.Namespace) -> str:
    if args.editing not in ("all", "own"):
        raise OperatorError("Editing must be 'all' or 'own'")

    set_task_editing(
        db, business_slug=args.business, email=args.email, edits_all=args.editing == "all"
    )
    return f"{args.email.strip()} now edits {args.editing} tasks."


def transfer_leadership_command(db: Session, args: argparse.Namespace) -> str:
    previous = transfer_leadership(db, business_slug=args.business, email=args.to)
    message = f"{args.to.strip()} is now the leader of {args.business.strip()!r}"
    return f"{message}; {previous} remains an admin." if previous else f"{message}."


def grant_task_view_command(db: Session, args: argparse.Namespace) -> str:
    viewer, owner = args.viewer.strip(), args.owner.strip()

    if grant_task_view(
        db, business_slug=args.business, viewer_email=viewer, owner_email=owner
    ):
        return f"{viewer} now sees the tasks of {owner} (view only)."
    return f"{viewer} already sees the tasks of {owner}; nothing changed."


def grant_task_edit_command(db: Session, args: argparse.Namespace) -> str:
    viewer, owner = args.viewer.strip(), args.owner.strip()

    if grant_task_edit(
        db, business_slug=args.business, viewer_email=viewer, owner_email=owner
    ):
        return f"{viewer} can now change the tasks of {owner}."
    return f"{viewer} can already change the tasks of {owner}; nothing changed."


def revoke_task_edit_command(db: Session, args: argparse.Namespace) -> str:
    viewer, owner = args.viewer.strip(), args.owner.strip()

    if revoke_task_edit(
        db, business_slug=args.business, viewer_email=viewer, owner_email=owner
    ):
        return f"{viewer} can no longer change the tasks of {owner}."
    return f"{viewer} had no edit grant for the tasks of {owner}; nothing changed."


def revoke_task_view_command(db: Session, args: argparse.Namespace) -> str:
    viewer, owner = args.viewer.strip(), args.owner.strip()

    if revoke_task_view(
        db, business_slug=args.business, viewer_email=viewer, owner_email=owner
    ):
        return f"{viewer} no longer sees the tasks of {owner}."
    return f"{viewer} had no grant for the tasks of {owner}; nothing changed."


def list_task_grants_command(db: Session, args: argparse.Namespace) -> str:
    rows = list_task_grants(db, args.business)

    if not rows:
        return f"No task grants in business {args.business.strip()!r}."

    return "\n".join(
        f"{row.viewer_email}  sees tasks of  {row.owner_email}  ({row.permission})"
        for row in rows
    )


DEFAULT_AUDIT_LIMIT = 50
# One command can never dump an enormous log.
MAX_AUDIT_LIMIT = 1000


def audit_limit(value: str | int | None) -> int:
    # From the menu the answer is text, or None when left blank.
    if value is None:
        return DEFAULT_AUDIT_LIMIT
    try:
        limit = int(value)
    except ValueError:
        limit = 0
    if not 1 <= limit <= MAX_AUDIT_LIMIT:
        raise OperatorError(f"Limit must be a whole number from 1 to {MAX_AUDIT_LIMIT}")
    return limit


def audit_log_command(db: Session, args: argparse.Namespace) -> str:
    slug = args.business.strip()
    # The latest events, printed oldest to newest like tail:
    # the most recent line ends up right above the prompt.
    events = list(reversed(list_audit_events(db, slug, audit_limit(args.limit))))

    if not events:
        return f"No audit events for business {slug!r}."

    lines = [
        f"{event.occurred_at.astimezone(timezone.utc):%Y-%m-%d %H:%M:%S} UTC  "
        f"{event.actor_email or 'operator'}  {event.action}  {event.target_email or '-'}  "
        + " ".join(f"{key}={value}" for key, value in sorted(event.details.items()))
        for event in events
    ]

    # A deleted business's slug can be reused by a new business.
    business_ids = sorted({event.business_id for event in events})
    if len(business_ids) > 1:
        lines.append(
            f"Note: these events belong to more than one business with this slug "
            f"(ids {', '.join(map(str, business_ids))})."
        )

    return "\n".join(lines)


def rename_business_command(db: Session, args: argparse.Namespace) -> str:
    previous = rename_business(db, slug=args.slug, name=args.name)
    business = get_business(db, args.slug)

    return (
        f"Renamed business {business.slug!r} "
        f"from {previous!r} to {business.name!r}."
    )


def delete_business_command(db: Session, args: argparse.Namespace) -> str:
    business = get_business(db, args.slug)
    # Checked before asking, so the operator never confirms a refused deletion.
    ensure_business_is_empty(db, business)
    slug, name = business.slug, business.name
    end_read_transaction(db)

    require_terminal()
    print(f"This permanently deletes business {slug!r} ({name}).")
    if ensure_readable(input("Type the slug again to confirm: ")).strip() != slug:
        raise OperatorError("Confirmation did not match; nothing was deleted")

    delete_business(db, slug=slug)

    return f"Deleted business {slug!r}."


Handler = Callable[[Session, argparse.Namespace], str]

# Each entry calls the same handler as its command,
# so the menu inherits every check, prompt and confirmation.
# Fields: (argument, question, required).
VIEW_GRANT_FIELDS = [
    ("business", "Business slug", True),
    ("viewer", "Viewer email (sees the tasks)", True),
    ("owner", "Owner email (whose tasks are shown)", True),
]
EDIT_GRANT_FIELDS = [
    ("business", "Business slug", True),
    ("viewer", "Editor email (may change the tasks)", True),
    ("owner", "Owner email (whose tasks may be changed)", True),
]
MUST_CHANGE_FIELD = (
    "must_change", "Must change password at next login? (yes/no, Enter for yes)", False
)

MENU: list[tuple[str, Handler, list[tuple[str, str, bool]]]] = [
    ("List users", list_users_command, [
        ("business", "Business slug (Enter for all)", False),
    ]),
    ("Create business", create_business, [
        ("name", "Business display name", True),
        ("slug", "Business slug", True),
        ("admin_email", "Admin email", True),
        MUST_CHANGE_FIELD,
    ]),
    ("Rename business", rename_business_command, [
        ("slug", "Business slug", True),
        ("name", "New display name", True),
    ]),
    ("Delete business", delete_business_command, [
        ("slug", "Business slug", True),
    ]),
    ("Add user", add_user_command, [
        ("business", "Business slug", True),
        ("email", "Email", True),
        ("role", "Role (admin/member)", True),
        MUST_CHANGE_FIELD,
    ]),
    ("Remove user", remove_user_command, [
        ("business", "Business slug", True),
        ("email", "Email", True),
    ]),
    ("Reassign tasks", reassign_tasks_command, [
        ("business", "Business slug", True),
        ("from_email", "Current owner email", True),
        ("to", "Receiving user email", True),
    ]),
    ("Reset password", reset_password_command, [
        ("business", "Business slug", True),
        ("email", "Email", True),
        MUST_CHANGE_FIELD,
    ]),
    ("End sessions", end_sessions_command, [
        ("business", "Business slug", True),
        ("email", "Email", True),
    ]),
    ("Change role", set_role_command, [
        ("business", "Business slug", True),
        ("email", "Email", True),
        ("role", "New role (admin/member)", True),
    ]),
    ("Transfer leadership", transfer_leadership_command, [
        ("business", "Business slug", True),
        ("to", "New leader email (an admin)", True),
    ]),
    ("Change task visibility", set_task_visibility_command, [
        ("business", "Business slug", True),
        ("email", "Email", True),
        ("visibility", "Visibility (all/own)", True),
    ]),
    ("Change task editing", set_task_editing_command, [
        ("business", "Business slug", True),
        ("email", "Email", True),
        ("editing", "Editing (all/own)", True),
    ]),
    ("Grant task view", grant_task_view_command, VIEW_GRANT_FIELDS),
    ("Grant task edit", grant_task_edit_command, EDIT_GRANT_FIELDS),
    ("Revoke task view", revoke_task_view_command, VIEW_GRANT_FIELDS),
    ("Revoke task edit", revoke_task_edit_command, EDIT_GRANT_FIELDS),
    ("List task grants", list_task_grants_command, [
        ("business", "Business slug", True),
    ]),
    ("Show audit log", audit_log_command, [
        ("business", "Business slug", True),
        ("limit", f"Number of events (Enter for {DEFAULT_AUDIT_LIMIT})", False),
    ]),
]


def ask_fields(fields: list[tuple[str, str, bool]]) -> argparse.Namespace | None:
    """The answers as command arguments, or None if the operator cancelled."""
    answers = {}

    for argument, question, required in fields:
        answer = ensure_readable(input(f"{question}: ").strip())

        if not answer and required:
            return None

        answers[argument] = answer or None

    return argparse.Namespace(**answers)


def run_menu(session_factory: Callable[[], Session]) -> int:
    require_terminal()

    try:
        while True:
            print("\nTask Manager operator menu")
            for number, (label, _, _) in enumerate(MENU, start=1):
                print(f"  {number}  {label}")
            print("  0  Exit")

            choice = input("Choice: ").strip()

            if choice == "0":
                return 0

            if not choice.isdigit() or not 1 <= int(choice) <= len(MENU):
                print(f"Unknown choice {choice!r}.")
                continue

            label, handler, fields = MENU[int(choice) - 1]
            print(f"\n{label} (leave an answer blank to cancel)")

            try:
                args = ask_fields(fields)
            except OperatorError as error:
                print(f"Error: {error}", file=sys.stderr)
                continue

            if args is None:
                print("Cancelled; nothing was changed.")
                continue

            # A fresh session per action: nothing stays open while the menu waits.
            db = session_factory()
            try:
                print(handler(db, args))
            except OperatorError as error:
                print(f"Error: {error}", file=sys.stderr)
            finally:
                db.close()
    except (KeyboardInterrupt, EOFError):
        # Each action saves in a single commit, so an interrupted one saved nothing.
        print("\nExited; an unfinished action was not saved.")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.backend.cli",
        description="Task Manager operator commands.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser(
        "create-business",
        help="Create a business and its first administrator.",
    )
    create.add_argument(
        "--name",
        required=True,
        help="Display name; Hebrew is supported.",
    )
    create.add_argument(
        "--slug",
        required=True,
        help="Login URL name: lowercase letters, digits and single hyphens.",
    )
    create.add_argument("--admin-email", required=True)
    create.add_argument("--permanent", action="store_true", help=PERMANENT_HELP)
    create.set_defaults(handler=create_business)

    listing = commands.add_parser(
        "list-users",
        help="List businesses and their users (read-only).",
    )
    listing.add_argument("--business", help="Only this business slug.")
    listing.set_defaults(handler=list_users_command)

    # Every user command names the business as well as the email,
    # so a user of another business cannot be changed by mistake.
    def user_command(name: str, help_text: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--business", required=True, help="Business slug.")
        command.add_argument("--email", required=True)
        return command

    add = user_command("add-user", "Add a user to an existing business.")
    add.add_argument("--role", required=True, choices=ROLES)
    add.add_argument("--permanent", action="store_true", help=PERMANENT_HELP)
    add.set_defaults(handler=add_user_command)

    reset = user_command("reset-password", "Set a new password for a user.")
    reset.add_argument("--permanent", action="store_true", help=PERMANENT_HELP)
    reset.set_defaults(handler=reset_password_command)

    ends = user_command("end-sessions", "Log a user out everywhere; the password is unchanged.")
    ends.set_defaults(handler=end_sessions_command)

    role = user_command("set-role", "Promote or demote a user.")
    role.add_argument("--role", required=True, choices=ROLES)
    role.set_defaults(handler=set_role_command)

    transfer = commands.add_parser(
        "transfer-leadership",
        help="Make an admin the business's leader; the previous leader stays an admin.",
    )
    transfer.add_argument("--business", required=True, help="Business slug.")
    transfer.add_argument("--to", required=True, help="Email of the new leader (an admin).")
    transfer.set_defaults(handler=transfer_leadership_command)

    visibility = user_command("set-task-visibility", "Choose which tasks a user sees.")
    choice = visibility.add_mutually_exclusive_group(required=True)
    choice.add_argument(
        "--all", dest="visibility", action="store_const", const="all",
        help="Every task in the business.",
    )
    choice.add_argument(
        "--own", dest="visibility", action="store_const", const="own",
        help="Only the user's own tasks.",
    )
    visibility.set_defaults(handler=set_task_visibility_command)

    editing = user_command("set-task-editing", "Choose which tasks a user may change.")
    edit_choice = editing.add_mutually_exclusive_group(required=True)
    edit_choice.add_argument(
        "--all", dest="editing", action="store_const", const="all",
        help="Every task in the business; requires seeing all tasks.",
    )
    edit_choice.add_argument(
        "--own", dest="editing", action="store_const", const="own",
        help="Only the user's own tasks.",
    )
    editing.set_defaults(handler=set_task_editing_command)

    remove = user_command("remove-user", "Delete a user and their tasks.")
    remove.set_defaults(handler=remove_user_command)

    reassign = commands.add_parser(
        "reassign-tasks",
        help="Move every task of one user to another user in the same business.",
    )
    reassign.add_argument("--business", required=True, help="Business slug.")
    reassign.add_argument(
        "--from", dest="from_email", required=True, help="Email of the current owner."
    )
    reassign.add_argument("--to", required=True, help="Email of the user receiving the tasks.")
    reassign.set_defaults(handler=reassign_tasks_command)

    # A grant names two users, so these take --viewer and --owner instead of --email.
    def grant_command(
        name: str, help_text: str, viewer_help: str, owner_help: str
    ) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--business", required=True, help="Business slug.")
        command.add_argument("--viewer", required=True, help=viewer_help)
        command.add_argument("--owner", required=True, help=owner_help)
        return command

    view_help = ("Email of who sees the tasks.", "Email of whose tasks are shown.")
    edit_help = ("Email of who may change the tasks.", "Email of whose tasks may be changed.")

    grant = grant_command(
        "grant-task-view", "Let a user see all tasks of another user.", *view_help
    )
    grant.set_defaults(handler=grant_task_view_command)

    revoke = grant_command("revoke-task-view", "Remove a task view grant.", *view_help)
    revoke.set_defaults(handler=revoke_task_view_command)

    grant_edit = grant_command(
        "grant-task-edit",
        "Let a user change all tasks of another user they can see.",
        *edit_help,
    )
    grant_edit.set_defaults(handler=grant_task_edit_command)

    revoke_edit = grant_command(
        "revoke-task-edit",
        "Remove a task edit grant; the user keeps seeing the tasks.",
        *edit_help,
    )
    revoke_edit.set_defaults(handler=revoke_task_edit_command)

    grants = commands.add_parser(
        "list-task-grants",
        help="List a business's task view and edit grants (read-only).",
    )
    grants.add_argument("--business", required=True, help="Business slug.")
    grants.set_defaults(handler=list_task_grants_command)

    audit = commands.add_parser(
        "audit-log",
        help="Show a business's latest recorded changes, oldest to newest (read-only).",
    )
    audit.add_argument(
        "--business",
        required=True,
        help="Business slug; also works for a deleted business.",
    )
    audit.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_AUDIT_LIMIT,
        help=f"How many events, 1 to {MAX_AUDIT_LIMIT} (default {DEFAULT_AUDIT_LIMIT}).",
    )
    audit.set_defaults(handler=audit_log_command)

    # The slug is not renamable: it will become the business's login URL.
    rename = commands.add_parser(
        "rename-business",
        help="Change a business's display name.",
    )
    rename.add_argument("--slug", required=True)
    rename.add_argument("--name", required=True, help="New display name.")
    rename.set_defaults(handler=rename_business_command)

    delete = commands.add_parser(
        "delete-business",
        help="Delete a business that has no users.",
    )
    delete.add_argument("--slug", required=True)
    delete.set_defaults(handler=delete_business_command)

    commands.add_parser(
        "menu",
        help="Interactive menu for all of the commands above.",
    )

    return parser


def main(
    argv: Sequence[str] | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> int:
    args = build_parser().parse_args(argv)

    try:
        # Command-line text is decoded the same way as typed answers.
        for value in vars(args).values():
            if isinstance(value, str):
                ensure_readable(value)

        with utf8_line_editing():
            if args.command == "menu":
                return run_menu(session_factory)

            db = session_factory()
            try:
                message = args.handler(db, args)
            finally:
                db.close()
    except OperatorError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        # Every command saves in a single commit, so an interrupted one saved nothing.
        # 130 is the conventional exit code for a Ctrl+C interruption.
        print("\nCancelled; nothing was saved.", file=sys.stderr)
        return 130

    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
