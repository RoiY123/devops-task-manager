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

from sqlalchemy.orm import Session

try:
    import termios
except ImportError:
    # Not available on Windows, where the tests may run; the CLI itself runs on Linux.
    termios = None

from app.backend.accounts import (
    ROLES,
    OperatorError,
    add_user,
    ensure_user_can_be_removed,
    find_user,
    get_business,
    grant_task_view,
    list_task_grants,
    list_users,
    remove_user,
    reset_password,
    revoke_task_view,
    set_role,
    set_task_visibility,
    transfer_leadership,
    validate_new_user,
)
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


def end_read_transaction(db: Session) -> None:
    # The checks opened a transaction; holding it while the operator types
    # would make a deploy's migration wait on its table locks.
    db.rollback()


def create_business(db: Session, args: argparse.Namespace) -> str:
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
    )

    return (
        f"Created business {result.slug!r} (id {result.business_id}) "
        f"with leader {result.admin_email} (user id {result.admin_user_id})."
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
            f"{'all tasks' if row.sees_all_tasks or row.is_leader else 'own tasks'}"
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
    )

    return (
        f"Added {user.role} {user.email} (user id {user.id}) "
        f"to business {args.business.strip()!r}"
        + (" as its leader." if user.is_leader else ".")
    )


def reset_password_command(db: Session, args: argparse.Namespace) -> str:
    user = find_user(db, business_slug=args.business, email=args.email)
    email = user.email
    end_read_transaction(db)

    password = read_new_password("New password")
    reset_password(
        db, business_slug=args.business, email=args.email, password=password
    )

    return (
        f"Password reset for {email}. "
        f"Logins made before the reset stay valid until their tokens expire."
    )


def set_role_command(db: Session, args: argparse.Namespace) -> str:
    previous = set_role(
        db, business_slug=args.business, email=args.email, role=args.role
    )

    if previous == args.role:
        return f"{args.email.strip()} is already {args.role}; nothing changed."

    return (
        f"Changed {args.email.strip()} from {previous} to {args.role}; "
        f"now {visibility_text(args.role == ROLE_ADMIN)}."
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


def set_task_visibility_command(db: Session, args: argparse.Namespace) -> str:
    if args.visibility not in ("all", "own"):
        raise OperatorError("Visibility must be 'all' or 'own'")

    sees_all = args.visibility == "all"
    set_task_visibility(
        db, business_slug=args.business, email=args.email, sees_all=sees_all
    )

    return f"{args.email.strip()} now {visibility_text(sees_all)}."


def transfer_leadership_command(db: Session, args: argparse.Namespace) -> str:
    previous = transfer_leadership(db, business_slug=args.business, email=args.to)
    message = f"{args.to.strip()} is now the leader of {args.business.strip()!r}"
    return f"{message}; {previous} remains an admin." if previous else f"{message}."


def grant_task_view_command(db: Session, args: argparse.Namespace) -> str:
    result = grant_task_view(
        db, business_slug=args.business, viewer_email=args.viewer, owner_email=args.owner
    )
    viewer, owner = args.viewer.strip(), args.owner.strip()

    if result.created:
        message = f"{viewer} now sees the tasks of {owner} (view only)."
    else:
        message = f"{viewer} already sees the tasks of {owner}; nothing changed."

    if result.viewer_sees_all:
        message += (
            f"\nNote: {viewer} already sees all tasks; "
            "the grant matters if their visibility changes to own."
        )
    return message


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
GRANT_FIELDS = [
    ("business", "Business slug", True),
    ("viewer", "Viewer email (sees the tasks)", True),
    ("owner", "Owner email (whose tasks are shown)", True),
]

MENU: list[tuple[str, Handler, list[tuple[str, str, bool]]]] = [
    ("List users", list_users_command, [
        ("business", "Business slug (Enter for all)", False),
    ]),
    ("Create business", create_business, [
        ("name", "Business display name", True),
        ("slug", "Business slug", True),
        ("admin_email", "Admin email", True),
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
    ]),
    ("Remove user", remove_user_command, [
        ("business", "Business slug", True),
        ("email", "Email", True),
    ]),
    ("Reset password", reset_password_command, [
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
    ("Grant task view", grant_task_view_command, GRANT_FIELDS),
    ("Revoke task view", revoke_task_view_command, GRANT_FIELDS),
    ("List task grants", list_task_grants_command, [
        ("business", "Business slug", True),
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
    add.set_defaults(handler=add_user_command)

    reset = user_command("reset-password", "Set a new password for a user.")
    reset.set_defaults(handler=reset_password_command)

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

    remove = user_command("remove-user", "Delete a user and their tasks.")
    remove.set_defaults(handler=remove_user_command)

    # A grant names two users, so these take --viewer and --owner instead of --email.
    def grant_command(name: str, help_text: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--business", required=True, help="Business slug.")
        command.add_argument("--viewer", required=True, help="Email of who sees the tasks.")
        command.add_argument("--owner", required=True, help="Email of whose tasks are shown.")
        return command

    grant = grant_command("grant-task-view", "Let a user see all tasks of another user.")
    grant.set_defaults(handler=grant_task_view_command)

    revoke = grant_command("revoke-task-view", "Remove a task view grant.")
    revoke.set_defaults(handler=revoke_task_view_command)

    grants = commands.add_parser(
        "list-task-grants",
        help="List a business's task view grants (read-only).",
    )
    grants.add_argument("--business", required=True, help="Business slug.")
    grants.set_defaults(handler=list_task_grants_command)

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
