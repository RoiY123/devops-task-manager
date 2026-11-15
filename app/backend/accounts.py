"""Account rules and the operator's user-management actions."""
import unicodedata
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, MultipleResultsFound
from sqlalchemy.orm import Session, aliased

from app.backend.models import (
    PERMISSION_VIEW,
    ROLE_ADMIN,
    ROLE_MEMBER,
    Business,
    TaskGrant,
    User,
)
from app.backend.security import hash_password


MAX_EMAIL_LENGTH = 320
MIN_PASSWORD_LENGTH = 12
ROLES = (ROLE_ADMIN, ROLE_MEMBER)


class OperatorError(ValueError):
    """Rejected operator input. The message is safe to show the operator."""


def reject_control_characters(text: str, label: str) -> None:
    # At the CLI's prompts, arrow keys insert escape sequences (ESC [ D) instead
    # of moving the cursor. Visible prompts show them as ^[[D, but at a password
    # prompt they go in unseen and would make the password impossible to type
    # on a website; pasted text can also bring tabs. Direction marks used in
    # Hebrew text are a different category (Cf) and stay allowed.
    if any(unicodedata.category(character) == "Cc" for character in text):
        raise OperatorError(
            f"{label} contains control characters (for example, from arrow keys); "
            f"retype it without using arrow keys"
        )


def clean_email(email: str) -> str:
    email = email.strip()
    reject_control_characters(email, "Email")

    if "@" not in email or len(email) > MAX_EMAIL_LENGTH:
        raise OperatorError(f"Email {email!r} is invalid")

    return email


def check_password(password: str) -> None:
    reject_control_characters(password, "Password")

    if len(password) < MIN_PASSWORD_LENGTH:
        raise OperatorError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        )


def ensure_email_is_free(db: Session, email: str, business: Business) -> None:
    # Unique per business, ignoring capitals, like uq_users_business_id_lower_email.
    taken = db.scalar(
        select(User.id).where(
            User.business_id == business.id,
            func.lower(User.email) == email.lower(),
        )
    )

    if taken is not None:
        raise OperatorError(
            f"Email {email!r} is already registered in business {business.slug!r}"
        )


def check_role(role: str) -> None:
    if role not in ROLES:
        raise OperatorError(f"Role {role!r} is invalid: use {' or '.join(ROLES)}")


def get_business(db: Session, slug: str, *, lock: bool = False) -> Business:
    query = select(Business).where(Business.slug == slug.strip())
    # The lock makes concurrent leader changes on one business wait their turn,
    # so none can leave it with no leader or a wrong one.
    business = db.scalar(query.with_for_update() if lock else query)

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


def user_count(db: Session, business_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.business_id == business_id)
    )


def ensure_user_can_be_removed(db: Session, user: User) -> None:
    # A business with users always has a leader, who is an admin.
    # An empty business is fine, so removing its last user is allowed.
    if user.is_leader and user_count(db, user.business_id) > 1:
        raise OperatorError(
            f"{user.email} is the leader of {user.business.slug!r}; "
            "transfer leadership to an admin first"
        )


@dataclass(frozen=True)
class UserListing:
    business_slug: str
    business_name: str
    # None for a business without users.
    user_id: int | None
    email: str | None
    role: str | None
    sees_all_tasks: bool | None
    is_leader: bool | None


def list_users(db: Session, business_slug: str | None = None) -> list[UserListing]:
    query = (
        select(
            Business.slug,
            Business.name,
            User.id,
            User.email,
            User.role,
            User.sees_all_tasks,
            Business.leader_user_id == User.id,
        )
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
    ensure_email_is_free(db, email, business)

    if role != ROLE_ADMIN and user_count(db, business.id) == 0:
        raise OperatorError(
            "The first user of an empty business becomes its leader; use --role admin"
        )

    return NewUser(business_id=business.id, email=email, role=role)


def add_user(
    db: Session,
    *,
    business_slug: str,
    email: str,
    role: str,
    password: str,
) -> User:
    business = get_business(db, business_slug, lock=True)
    # Validated again here: the email may have been taken
    # while the operator was typing the password.
    new = validate_new_user(db, business_slug=business_slug, email=email, role=role)
    check_password(password)
    becomes_leader = business.leader_user_id is None and user_count(db, business.id) == 0

    user = User(
        email=new.email,
        hashed_password=hash_password(password),
        business_id=new.business_id,
        role=new.role,
        # Admins see every task by default; members only their own.
        sees_all_tasks=new.role == ROLE_ADMIN,
    )
    db.add(user)

    try:
        if becomes_leader:
            # The user needs an id before the business can point at it;
            # both changes are saved by the same commit.
            db.flush()
            business.leader_user_id = user.id
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

    if previous == role:
        return previous

    if user.is_leader:
        raise OperatorError(
            f"{user.email} is the leader of {user.business.slug!r}; "
            "transfer leadership first"
        )

    user.role = role
    # A role change applies that role's default; set-task-visibility adjusts it.
    user.sees_all_tasks = role == ROLE_ADMIN
    db.commit()

    return previous


def set_task_visibility(
    db: Session, *, business_slug: str, email: str, sees_all: bool
) -> None:
    user = find_user(db, business_slug=business_slug, email=email)

    if user.is_leader:
        raise OperatorError(f"{user.email} is the leader; the leader always sees all tasks")

    user.sees_all_tasks = sees_all
    db.commit()


def transfer_leadership(db: Session, *, business_slug: str, email: str) -> str | None:
    """Make an admin the leader; return the previous leader's email, if any."""
    business = get_business(db, business_slug, lock=True)
    new_leader = find_user(db, business_slug=business_slug, email=email)

    if new_leader.role != ROLE_ADMIN:
        raise OperatorError(
            f"{new_leader.email} is a {new_leader.role}; promote them to admin first"
        )
    if business.leader_user_id == new_leader.id:
        raise OperatorError(f"{new_leader.email} is already the leader")

    previous = db.get(User, business.leader_user_id) if business.leader_user_id else None
    business.leader_user_id = new_leader.id
    # Kept consistent for images that read only this setting.
    new_leader.sees_all_tasks = True
    db.commit()

    return previous.email if previous else None


@dataclass(frozen=True)
class GrantResult:
    created: bool
    # A grant adds nothing while the viewer sees all tasks; the CLI says so.
    viewer_sees_all: bool


@dataclass(frozen=True)
class GrantListing:
    viewer_email: str
    owner_email: str
    permission: str


def find_grant_users(
    db: Session, *, business_slug: str, viewer_email: str, owner_email: str
) -> tuple[User, User]:
    viewer = find_user(db, business_slug=business_slug, email=viewer_email)
    owner = find_user(db, business_slug=business_slug, email=owner_email)

    if viewer.id == owner.id:
        raise OperatorError("A user always sees their own tasks; choose two different users")

    return viewer, owner


def grant_task_view(
    db: Session, *, business_slug: str, viewer_email: str, owner_email: str
) -> GrantResult:
    """Let the viewer see every task of the owner; repeating it changes nothing."""
    viewer, owner = find_grant_users(
        db, business_slug=business_slug, viewer_email=viewer_email, owner_email=owner_email
    )
    created = db.get(TaskGrant, (viewer.id, owner.id)) is None

    if created:
        db.add(
            TaskGrant(
                viewer_id=viewer.id,
                owner_id=owner.id,
                business_id=viewer.business_id,
                permission=PERMISSION_VIEW,
            )
        )
        db.commit()

    return GrantResult(created=created, viewer_sees_all=viewer.sees_all_tasks)


def revoke_task_view(
    db: Session, *, business_slug: str, viewer_email: str, owner_email: str
) -> bool:
    """Remove the grant; return False if there was none."""
    viewer, owner = find_grant_users(
        db, business_slug=business_slug, viewer_email=viewer_email, owner_email=owner_email
    )
    grant = db.get(TaskGrant, (viewer.id, owner.id))

    if grant is None:
        return False

    db.delete(grant)
    db.commit()
    return True


def list_task_grants(db: Session, business_slug: str) -> list[GrantListing]:
    business = get_business(db, business_slug)
    viewer, owner = aliased(User), aliased(User)
    query = (
        select(viewer.email, owner.email, TaskGrant.permission)
        .join(viewer, viewer.id == TaskGrant.viewer_id)
        .join(owner, owner.id == TaskGrant.owner_id)
        .where(TaskGrant.business_id == business.id)
        .order_by(viewer.email, owner.email)
    )
    return [GrantListing(*row) for row in db.execute(query)]


def remove_user(db: Session, *, business_slug: str, email: str) -> int:
    """Delete the user and their tasks; return how many tasks were deleted."""
    business = get_business(db, business_slug, lock=True)
    user = find_user(db, business_slug=business_slug, email=email)
    ensure_user_can_be_removed(db, user)

    task_count = len(user.tasks)

    if user.is_leader:
        # The last user: the business may become empty, but the foreign key
        # refuses deleting a recorded leader, so clear it first.
        business.leader_user_id = None
        db.flush()

    # User.tasks cascades, so the user's tasks are deleted in the same commit.
    db.delete(user)
    db.commit()

    return task_count
