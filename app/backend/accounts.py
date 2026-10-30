"""Account rules and the operator's user-management actions."""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, MultipleResultsFound
from sqlalchemy.orm import Session

from app.backend.models import ROLE_ADMIN, ROLE_MEMBER, Business, User
from app.backend.security import hash_password


MAX_EMAIL_LENGTH = 320
MIN_PASSWORD_LENGTH = 12
ROLES = (ROLE_ADMIN, ROLE_MEMBER)


class OperatorError(ValueError):
    """Rejected operator input. The message is safe to show the operator."""


def clean_email(email: str) -> str:
    email = email.strip()

    if "@" not in email or len(email) > MAX_EMAIL_LENGTH:
        raise OperatorError(f"Email {email!r} is invalid")

    return email


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise OperatorError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        )


def ensure_email_is_free(db: Session, email: str) -> None:
    # Email is still unique across all businesses until business-specific login exists.
    # Compared case-insensitively so Dana@x and dana@x cannot become two accounts.
    taken = db.scalar(
        select(User.id).where(func.lower(User.email) == email.lower())
    )

    if taken is not None:
        raise OperatorError(f"Email {email!r} is already registered")


def check_role(role: str) -> None:
    if role not in ROLES:
        raise OperatorError(f"Role {role!r} is invalid: use {' or '.join(ROLES)}")


def get_business(db: Session, slug: str) -> Business:
    business = db.scalar(select(Business).where(Business.slug == slug.strip()))

    if business is None:
        raise OperatorError(f"No business with slug {slug.strip()!r}")

    return business


def find_user(db: Session, *, business_slug: str, email: str) -> User:
    """The user with this email in this business; a user in another business is not found."""
    business = get_business(db, business_slug)
    email = email.strip()

    try:
        user = db.scalars(
            select(User).where(
                User.business_id == business.id,
                func.lower(User.email) == email.lower(),
            )
        ).one_or_none()
    except MultipleResultsFound:
        # Possible only for accounts created before the case-insensitive check.
        raise OperatorError(
            f"Several users match {email!r} ignoring capitalisation; resolve manually"
        ) from None

    if user is None:
        raise OperatorError(f"No user {email!r} in business {business.slug!r}")

    return user


def ensure_business_keeps_an_admin(
    db: Session,
    user: User,
    *,
    removing: bool,
) -> None:
    # Users without an admin could not be managed inside their business.
    # An empty business is fine, so removing its last user is allowed.
    if user.role != ROLE_ADMIN:
        return

    others = select(func.count()).select_from(User).where(
        User.business_id == user.business_id,
        User.id != user.id,
    )

    if db.scalar(others.where(User.role == ROLE_ADMIN)) > 0:
        return

    if removing and db.scalar(others) == 0:
        return

    raise OperatorError(
        f"{user.email} is the only admin of {user.business.slug!r}; "
        f"promote another user to admin first"
    )


@dataclass(frozen=True)
class UserListing:
    business_slug: str
    business_name: str
    # None for a business without users.
    user_id: int | None
    email: str | None
    role: str | None


def list_users(db: Session, business_slug: str | None = None) -> list[UserListing]:
    query = (
        select(Business.slug, Business.name, User.id, User.email, User.role)
        .outerjoin(User, User.business_id == Business.id)
        .order_by(Business.slug, User.id)
    )

    if business_slug is not None:
        query = query.where(Business.id == get_business(db, business_slug).id)

    return [UserListing(*row) for row in db.execute(query)]


@dataclass(frozen=True)
class NewUser:
    business_id: int
    email: str
    role: str


def validate_new_user(
    db: Session,
    *,
    business_slug: str,
    email: str,
    role: str,
) -> NewUser:
    """Check everything except the password, so the CLI can fail before prompting."""
    check_role(role)
    business = get_business(db, business_slug)
    email = clean_email(email)
    ensure_email_is_free(db, email)

    return NewUser(business_id=business.id, email=email, role=role)


def add_user(
    db: Session,
    *,
    business_slug: str,
    email: str,
    role: str,
    password: str,
) -> User:
    # Validated again here: the email may have been taken
    # while the operator was typing the password.
    new = validate_new_user(db, business_slug=business_slug, email=email, role=role)
    check_password(password)

    user = User(
        email=new.email,
        hashed_password=hash_password(password),
        business_id=new.business_id,
        role=new.role,
    )
    db.add(user)

    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise OperatorError(
            f"Email {new.email!r} was taken while adding the user; nothing was created"
        ) from error

    return user


def reset_password(
    db: Session,
    *,
    business_slug: str,
    email: str,
    password: str,
) -> None:
    # Tokens issued before the reset stay valid until they expire.
    user = find_user(db, business_slug=business_slug, email=email)
    check_password(password)

    user.hashed_password = hash_password(password)
    db.commit()


def set_role(
    db: Session,
    *,
    business_slug: str,
    email: str,
    role: str,
) -> str:
    """Change the user's role and return the previous one."""
    check_role(role)
    user = find_user(db, business_slug=business_slug, email=email)
    previous = user.role

    if previous == ROLE_ADMIN and role != ROLE_ADMIN:
        ensure_business_keeps_an_admin(db, user, removing=False)

    user.role = role
    db.commit()

    return previous


def remove_user(db: Session, *, business_slug: str, email: str) -> int:
    """Delete the user and their tasks; return how many tasks were deleted."""
    user = find_user(db, business_slug=business_slug, email=email)
    ensure_business_keeps_an_admin(db, user, removing=True)

    task_count = len(user.tasks)

    # User.tasks cascades, so the user's tasks are deleted in the same commit.
    db.delete(user)
    db.commit()

    return task_count
