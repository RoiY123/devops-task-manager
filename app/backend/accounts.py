"""Account rules and the operator's user-management actions."""
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError, MultipleResultsFound
from sqlalchemy.orm import Session, aliased

from app.backend.audit import record
from app.backend.models import (
    PERMISSION_EDIT,
    PERMISSION_VIEW,
    ROLE_ADMIN,
    ROLE_MEMBER,
    Business,
    Task,
    TaskGrant,
    User,
)
from app.backend.security import hash_password, verify_login_password


MAX_EMAIL_LENGTH = 320
MIN_PASSWORD_LENGTH = 12
# Far beyond any real password; keeps input reasonable.
MAX_PASSWORD_LENGTH = 256
# A password someone else chose stops working after this long unless replaced.
TEMPORARY_PASSWORD_LIFETIME = timedelta(days=7)
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

    if len(password) > MAX_PASSWORD_LENGTH:
        raise OperatorError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters"
        )


def temporary_password_expiry(temporary: bool) -> datetime | None:
    """The value for users.temporary_password_expires_at; None means a normal password."""
    return datetime.now(timezone.utc) + TEMPORARY_PASSWORD_LIFETIME if temporary else None


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
    edits_all_tasks: bool | None
    has_grants: bool | None
    has_edit_grants: bool | None

    # "custom" is not stored: it is own tasks plus the users granted.
    @property
    def view_level(self) -> str:
        if self.is_leader or self.sees_all_tasks:
            return "all"
        return "custom" if self.has_grants else "own"

    @property
    def edit_level(self) -> str:
        if self.is_leader or self.edits_all_tasks:
            return "all"
        return "custom" if self.has_edit_grants else "own"


def list_users(db: Session, business_slug: str | None = None) -> list[UserListing]:
    grants = select(TaskGrant.owner_id).where(TaskGrant.viewer_id == User.id)
    query = (
        select(
            Business.slug,
            Business.name,
            User.id,
            User.email,
            User.role,
            User.sees_all_tasks,
            Business.leader_user_id == User.id,
            User.edits_all_tasks,
            grants.exists(),
            grants.where(TaskGrant.permission == PERMISSION_EDIT).exists(),
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
    actor: User | None = None,
    temporary: bool = True,
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
        temporary_password_expires_at=temporary_password_expiry(temporary),
    )
    db.add(user)

    try:
        # The user needs an id before the business can point at it and the
        # event can name it; everything is saved by the same commit.
        db.flush()
        if becomes_leader:
            business.leader_user_id = user.id
        record(
            db,
            business=business,
            actor=actor,
            action="user_added",
            target=user,
            role=user.role,
            leader=becomes_leader,
            temporary=temporary,
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise OperatorError(
            f"Email {new.email!r} was taken while adding the user; nothing was created"
        ) from error

    return user


def end_sessions_of(user: User) -> None:
    """Refuse every login token the user was given until now."""
    # The app's clock, the same one that stamps iat on tokens;
    # the database's clock (on another machine) could be slightly off from it.
    user.tokens_valid_after = datetime.now(timezone.utc)


def reset_password(
    db: Session,
    *,
    business_slug: str,
    email: str,
    password: str,
    actor: User | None = None,
    temporary: bool = True,
) -> None:
    user = find_user(db, business_slug=business_slug, email=email)
    check_password(password)

    user.hashed_password = hash_password(password)
    user.temporary_password_expires_at = temporary_password_expiry(temporary)
    # Whoever knew the old password may still be logged in.
    end_sessions_of(user)
    # Record only that it happened; never the password.
    record(
        db, business=user.business, actor=actor, action="password_reset", target=user,
        temporary=temporary,
    )
    db.commit()


def end_sessions(
    db: Session,
    *,
    business_slug: str,
    email: str,
    actor: User | None = None,
) -> User:
    """Log the user out everywhere; the password stays the same."""
    user = find_user(db, business_slug=business_slug, email=email)
    end_sessions_of(user)
    record(db, business=user.business, actor=actor, action="sessions_ended", target=user)
    db.commit()
    return user


def change_own_password(
    db: Session, *, user: User, current_password: str, new_password: str
) -> None:
    """The user's own change; the current password proves it is really them."""
    # Locked and re-read first: a reset saved meanwhile is checked, never overwritten.
    db.refresh(user, with_for_update=True)
    if not verify_login_password(current_password, user.hashed_password):
        raise OperatorError("Current password is incorrect")
    if new_password == current_password:
        raise OperatorError("New password must differ from the current one")
    check_password(new_password)

    user.hashed_password = hash_password(new_password)
    # The user chose this one, so it is no longer temporary.
    user.temporary_password_expires_at = None
    # Every login ends, this device's included; the endpoint hands it a new token.
    end_sessions_of(user)
    record(db, business=user.business, actor=user, action="password_changed", target=user)
    db.commit()


def delete_grants_of(db: Session, viewer: User, permission: str | None = None) -> int:
    """Delete the viewer's grants and return how many there were."""
    query = delete(TaskGrant).where(TaskGrant.viewer_id == viewer.id)
    if permission is not None:
        query = query.where(TaskGrant.permission == permission)
    return db.execute(query).rowcount


def apply_role_defaults(db: Session, user: User) -> None:
    # Admins see all and members their own; everyone edits their own.
    # Grants chosen for the previous role are dropped, so none linger unnoticed.
    user.sees_all_tasks = user.role == ROLE_ADMIN
    user.edits_all_tasks = False
    delete_grants_of(db, user)


def ensure_not_leader(user: User, reason: str) -> None:
    if user.is_leader:
        raise OperatorError(f"{user.email} is the leader; the leader always {reason}")


def set_role(
    db: Session,
    *,
    business_slug: str,
    email: str,
    role: str,
    actor: User | None = None,
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
    apply_role_defaults(db, user)
    record(
        db,
        business=user.business,
        actor=actor,
        action="role_changed",
        target=user,
        **{"from": previous, "to": role},
    )
    db.commit()

    return previous


def set_task_visibility(
    db: Session,
    *,
    business_slug: str,
    email: str,
    sees_all: bool,
    actor: User | None = None,
) -> None:
    user = find_user(db, business_slug=business_slug, email=email)
    ensure_not_leader(user, "sees all tasks")

    if user.role == ROLE_ADMIN:
        raise OperatorError(f"{user.email} is an admin; admins always see all tasks")

    changed = user.sees_all_tasks != sees_all
    if sees_all:
        # Seeing all makes view grants redundant; edit grants still add editing.
        removed = delete_grants_of(db, user, PERMISSION_VIEW)
    else:
        # Only their own tasks: nothing else to see, so nothing else to edit.
        user.edits_all_tasks = False
        removed = delete_grants_of(db, user)

    user.sees_all_tasks = sees_all
    if changed or removed:
        record(
            db,
            business=user.business,
            actor=actor,
            action="task_visibility_changed",
            target=user,
            to="all" if sees_all else "own",
            grants_removed=removed,
        )
    db.commit()


def set_task_editing(
    db: Session,
    *,
    business_slug: str,
    email: str,
    edits_all: bool,
    actor: User | None = None,
) -> None:
    user = find_user(db, business_slug=business_slug, email=email)
    ensure_not_leader(user, "edits all tasks")

    changed = user.edits_all_tasks != edits_all
    if edits_all:
        if not user.sees_all_tasks:
            raise OperatorError(
                f"{user.email} does not see all tasks; set visibility to all first"
            )
        # Editing all covers every grant.
        affected = delete_grants_of(db, user)
    elif user.sees_all_tasks:
        affected = delete_grants_of(db, user, PERMISSION_EDIT)
    else:
        # Keep seeing what the edit grants showed, without changing it.
        affected = db.execute(
            update(TaskGrant)
            .where(TaskGrant.viewer_id == user.id, TaskGrant.permission == PERMISSION_EDIT)
            .values(permission=PERMISSION_VIEW)
        ).rowcount

    user.edits_all_tasks = edits_all
    if changed or affected:
        record(
            db,
            business=user.business,
            actor=actor,
            action="task_editing_changed",
            target=user,
            to="all" if edits_all else "own",
            grants_changed=affected,
        )
    db.commit()


def transfer_leadership(
    db: Session, *, business_slug: str, email: str, actor: User | None = None
) -> str | None:
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
    if previous is not None:
        # Back to an ordinary admin; the new leader can widen this.
        apply_role_defaults(db, previous)
    record(
        db,
        business=business,
        actor=actor,
        action="leadership_transferred",
        target=new_leader,
        previous_leader_email=previous.email if previous else None,
    )
    db.commit()

    return previous.email if previous else None


@dataclass(frozen=True)
class GrantListing:
    viewer_id: int
    viewer_email: str
    owner_id: int
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


def record_grant(
    db: Session, actor: User | None, action: str, viewer: User, owner: User
) -> None:
    record(
        db,
        business=viewer.business,
        actor=actor,
        action=action,
        target=viewer,
        owner_id=owner.id,
        owner_email=owner.email,
    )


def grant_task_view(
    db: Session,
    *,
    business_slug: str,
    viewer_email: str,
    owner_email: str,
    actor: User | None = None,
) -> bool:
    """Let the viewer see every task of the owner; return False if they already could."""
    viewer, owner = find_grant_users(
        db, business_slug=business_slug, viewer_email=viewer_email, owner_email=owner_email
    )

    if viewer.sees_all_tasks or viewer.is_leader:
        raise OperatorError(f"{viewer.email} already sees all tasks")

    # An existing grant, view or edit, already shows the tasks.
    if db.get(TaskGrant, (viewer.id, owner.id)) is not None:
        return False

    db.add(
        TaskGrant(
            viewer_id=viewer.id,
            owner_id=owner.id,
            business_id=viewer.business_id,
            permission=PERMISSION_VIEW,
        )
    )
    record_grant(db, actor, "view_granted", viewer, owner)
    db.commit()
    return True


def grant_task_edit(
    db: Session,
    *,
    business_slug: str,
    viewer_email: str,
    owner_email: str,
    actor: User | None = None,
) -> bool:
    """Let the viewer change every task of the owner; return False if they already could."""
    viewer, owner = find_grant_users(
        db, business_slug=business_slug, viewer_email=viewer_email, owner_email=owner_email
    )
    ensure_not_leader(viewer, "edits all tasks")

    if viewer.edits_all_tasks:
        raise OperatorError(f"{viewer.email} already edits all tasks")

    grant = db.get(TaskGrant, (viewer.id, owner.id))

    if grant is not None and grant.permission == PERMISSION_EDIT:
        return False

    # Edit access never exceeds view access.
    if grant is None and not viewer.sees_all_tasks:
        raise OperatorError(
            f"{viewer.email} cannot see the tasks of {owner.email}; grant view first"
        )

    if grant is None:
        db.add(
            TaskGrant(
                viewer_id=viewer.id,
                owner_id=owner.id,
                business_id=viewer.business_id,
                permission=PERMISSION_EDIT,
            )
        )
    else:
        grant.permission = PERMISSION_EDIT

    record_grant(db, actor, "edit_granted", viewer, owner)
    db.commit()
    return True


def revoke_task_edit(
    db: Session,
    *,
    business_slug: str,
    viewer_email: str,
    owner_email: str,
    actor: User | None = None,
) -> bool:
    """Stop the viewer changing the owner's tasks; return False if they could not."""
    viewer, owner = find_grant_users(
        db, business_slug=business_slug, viewer_email=viewer_email, owner_email=owner_email
    )
    grant = db.get(TaskGrant, (viewer.id, owner.id))

    if grant is None or grant.permission != PERMISSION_EDIT:
        return False

    if viewer.sees_all_tasks:
        # A view grant would add nothing to seeing all.
        db.delete(grant)
    else:
        # They keep seeing the tasks, without changing them.
        grant.permission = PERMISSION_VIEW

    record_grant(db, actor, "edit_revoked", viewer, owner)
    db.commit()
    return True


def revoke_task_view(
    db: Session,
    *,
    business_slug: str,
    viewer_email: str,
    owner_email: str,
    actor: User | None = None,
) -> bool:
    """Remove the grant; return False if there was none."""
    viewer, owner = find_grant_users(
        db, business_slug=business_slug, viewer_email=viewer_email, owner_email=owner_email
    )
    grant = db.get(TaskGrant, (viewer.id, owner.id))

    if grant is None:
        return False

    db.delete(grant)
    record_grant(db, actor, "view_revoked", viewer, owner)
    db.commit()
    return True


def list_task_grants(db: Session, business_slug: str) -> list[GrantListing]:
    business = get_business(db, business_slug)
    viewer, owner = aliased(User), aliased(User)
    query = (
        select(viewer.id, viewer.email, owner.id, owner.email, TaskGrant.permission)
        .join(viewer, viewer.id == TaskGrant.viewer_id)
        .join(owner, owner.id == TaskGrant.owner_id)
        .where(TaskGrant.business_id == business.id)
        .order_by(viewer.email, owner.email)
    )
    return [GrantListing(*row) for row in db.execute(query)]


def remove_user(
    db: Session, *, business_slug: str, email: str, actor: User | None = None
) -> int:
    """Delete the user and their tasks; return how many tasks were deleted."""
    business = get_business(db, business_slug, lock=True)
    user = find_user(db, business_slug=business_slug, email=email)
    ensure_user_can_be_removed(db, user)

    task_count = len(user.tasks)
    # Written while the user still exists; the event outlives them.
    record(
        db,
        business=business,
        actor=actor,
        action="user_removed",
        target=user,
        tasks_deleted=task_count,
    )

    if user.is_leader:
        # The last user: the business may become empty, but the foreign key
        # refuses deleting a recorded leader, so clear it first.
        business.leader_user_id = None
        db.flush()

    # User.tasks cascades, so the user's tasks are deleted in the same commit.
    db.delete(user)
    db.commit()

    return task_count


@dataclass(frozen=True)
class Reassignment:
    tasks_moved: int
    # People who saw or changed the tasks through a grant on their previous owner,
    # and no longer can.
    people_losing_access: int


def people_losing_access(db: Session, owner_ids: set[int], receiver: User) -> int:
    """Grant holders on a previous owner who no longer see or change the moved tasks."""
    on_receiver = aliased(TaskGrant)
    return db.scalar(
        select(func.count(func.distinct(TaskGrant.viewer_id)))
        .join(User, User.id == TaskGrant.viewer_id)
        .outerjoin(
            on_receiver,
            (on_receiver.viewer_id == TaskGrant.viewer_id) & (on_receiver.owner_id == receiver.id),
        )
        .where(
            TaskGrant.owner_id.in_(owner_ids),
            TaskGrant.viewer_id != receiver.id,
            # Editing all, or leading, keeps every access whoever owns the tasks.
            ~User.edits_all_tasks,
            User.id != receiver.business.leader_user_id,
            # No grant on the receiver, or only view where they could edit before.
            or_(
                on_receiver.viewer_id.is_(None),
                (TaskGrant.permission == PERMISSION_EDIT)
                & (on_receiver.permission == PERMISSION_VIEW),
            ),
        )
    )


def move_tasks(
    db: Session, *, tasks: Sequence[Task], receiver: User, actor: User | None = None
) -> Reassignment:
    """Give the tasks to the receiver and record it; the caller commits."""
    moving = [task for task in tasks if task.owner_id != receiver.id]
    if not moving:
        return Reassignment(tasks_moved=0, people_losing_access=0)

    previous = Counter(task.owner.email for task in moving)
    # Counted before the move, while the grants still point at the previous owners.
    losing = people_losing_access(db, {task.owner_id for task in moving}, receiver)
    for task in moving:
        task.owner = receiver
    record(
        db,
        business=receiver.business,
        actor=actor,
        action="tasks_reassigned",
        target=receiver,
        task_ids=sorted(task.id for task in moving),
        from_owners=dict(previous),
    )
    return Reassignment(tasks_moved=len(moving), people_losing_access=losing)


def reassign_tasks(
    db: Session, *, tasks: Sequence[Task], receiver: User, actor: User | None = None
) -> Reassignment:
    """Specific tasks, already checked by the caller."""
    result = move_tasks(db, tasks=tasks, receiver=receiver, actor=actor)
    db.commit()
    return result


def reassign_all_tasks(
    db: Session,
    *,
    business_slug: str,
    from_email: str,
    to_email: str,
    actor: User | None = None,
) -> Reassignment:
    """Every task of one user, for the operator and the user-level endpoint."""
    source = find_user(db, business_slug=business_slug, email=from_email)
    receiver = find_user(db, business_slug=business_slug, email=to_email)
    if source.id == receiver.id:
        raise OperatorError(f"{source.email} already owns these tasks; choose another user")

    # Locked: a task created for the source meanwhile waits, then is moved too or not at all.
    db.refresh(source, with_for_update=True)
    tasks = db.scalars(select(Task).where(Task.owner_id == source.id)).all()
    result = move_tasks(db, tasks=tasks, receiver=receiver, actor=actor)
    db.commit()
    return result
