"""Operator commands, run inside the API container.

Examples:
    python -m app.backend.cli create-business \
        --name "אינסטלציה כהן" --slug cohen-plumbing \
        --admin-email dana@cohen.example
    python -m app.backend.cli list-users --business cohen-plumbing
    python -m app.backend.cli add-user \
        --business cohen-plumbing --email avi@cohen.example --role member
"""
import argparse
import getpass
import sys
from collections.abc import Callable, Sequence

from sqlalchemy.orm import Session

from app.backend.accounts import (
    ROLES,
    OperatorError,
    add_user,
    ensure_business_keeps_an_admin,
    find_user,
    list_users,
    remove_user,
    reset_password,
    set_role,
    validate_new_user,
)
from app.backend.database import SessionLocal
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


def read_new_password(label: str) -> str:
    require_terminal()

    password = getpass.getpass(f"{label}: ")
    confirmation = getpass.getpass(f"Repeat {label.lower()}: ")

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
        f"with administrator {result.admin_email} (user id {result.admin_user_id})."
    )


def list_users_command(db: Session, args: argparse.Namespace) -> str:
    rows = list_users(db, args.business)

    if not rows:
        return "No businesses."

    return "\n".join(
        f"{row.business_slug}  ({row.business_name})  "
        + (
            f"user {row.user_id}  {row.email}  {row.role}"
            if row.user_id is not None
            else "no users"
        )
        for row in rows
    )


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
        f"to business {args.business.strip()!r}."
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

    return f"Changed {args.email.strip()} from {previous} to {args.role}."


def remove_user_command(db: Session, args: argparse.Namespace) -> str:
    user = find_user(db, business_slug=args.business, email=args.email)
    # Checked before asking, so the operator never confirms a refused removal.
    ensure_business_keeps_an_admin(db, user, removing=True)
    email = user.email
    task_count = len(user.tasks)
    end_read_transaction(db)

    require_terminal()
    print(f"This permanently deletes {email} and their {task_count} tasks.")
    if input("Type the email again to confirm: ").strip() != email:
        raise OperatorError("Confirmation did not match; nothing was deleted")

    deleted_tasks = remove_user(db, business_slug=args.business, email=email)

    return (
        f"Removed {email} from business {args.business.strip()!r} "
        f"and deleted {deleted_tasks} tasks."
    )


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

    remove = user_command("remove-user", "Delete a user and their tasks.")
    remove.set_defaults(handler=remove_user_command)

    return parser


def main(
    argv: Sequence[str] | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> int:
    args = build_parser().parse_args(argv)

    db = session_factory()
    try:
        message = args.handler(db, args)
    except OperatorError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
