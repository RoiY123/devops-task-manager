"""Operator commands, run inside the API container.

Example:
    python -m app.backend.cli create-business \
        --name "אינסטלציה כהן" --slug cohen-plumbing \
        --admin-email dana@cohen.example
"""
import argparse
import getpass
import sys
from collections.abc import Callable, Sequence

from sqlalchemy.orm import Session

from app.backend.database import SessionLocal
from app.backend.onboarding import OnboardingError, create_business_with_admin


def read_new_password() -> str:
    # getpass can hide typing only on an interactive terminal.
    # Refusing otherwise ensures a password is never echoed or piped in.
    if not sys.stdin.isatty():
        raise OnboardingError(
            "Run this command interactively "
            "(for example, docker compose exec without -T)"
        )

    password = getpass.getpass("Admin password: ")
    confirmation = getpass.getpass("Repeat admin password: ")

    if password != confirmation:
        raise OnboardingError("Passwords do not match; nothing was created")

    return password


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

    return parser


def main(
    argv: Sequence[str] | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> int:
    args = build_parser().parse_args(argv)

    try:
        password = read_new_password()

        db = session_factory()
        try:
            result = create_business_with_admin(
                db,
                name=args.name,
                slug=args.slug,
                admin_email=args.admin_email,
                admin_password=password,
            )
        finally:
            db.close()
    except OnboardingError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(
        f"Created business {result.slug!r} (id {result.business_id}) "
        f"with administrator {result.admin_email} (user id {result.admin_user_id})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
