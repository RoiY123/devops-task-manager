"""Who may manage whom through the API.

The operator's CLI does not use these checks: the operator may change anyone.
They decide only who may act; the account functions still keep the data valid
(for example, admins always see all tasks).
"""
from sqlalchemy.orm import Session

from app.backend.models import PERMISSION_EDIT, ROLE_ADMIN, ROLE_MEMBER, User
from app.backend.visibility import can_change_tasks_of


class ActionNotAllowed(Exception):
    """A refused management action. The message is safe to show the user."""


def ensure_same_business(actor: User, user: User) -> None:
    # Reported like a missing user, so other businesses' users are not revealed.
    if user.business_id != actor.business_id:
        raise ActionNotAllowed("User not found")


def ensure_can_manage(actor: User, target: User) -> None:
    """The rules every action on another user shares."""
    ensure_same_business(actor, target)
    if target.id == actor.id:
        raise ActionNotAllowed("You cannot change your own role or access")
    if target.is_leader:
        raise ActionNotAllowed("The leader's role and access cannot be changed")
    if actor.is_leader:
        return
    if actor.role != ROLE_ADMIN:
        raise ActionNotAllowed("Only the leader and admins can manage users")
    if target.role != ROLE_MEMBER:
        raise ActionNotAllowed("Admins can manage only members")


def check_set_role(actor: User, target: User) -> None:
    # Admins manage only members, so for them this can only promote.
    ensure_can_manage(actor, target)


def check_set_visibility(actor: User, target: User) -> None:
    # Admins see all tasks, so any visibility they give is within their own.
    ensure_can_manage(actor, target)


def check_set_editing(actor: User, target: User, *, edits_all: bool) -> None:
    ensure_can_manage(actor, target)
    if edits_all and not (actor.is_leader or actor.edits_all_tasks):
        raise ActionNotAllowed("You can let others edit all tasks only if you edit all tasks")


def check_grant(
    db: Session, actor: User, viewer: User, owner: User, *, permission: str
) -> None:
    ensure_can_manage(actor, viewer)
    ensure_same_business(actor, owner)
    # Never give more than you have: an edit grant needs the actor's own edit access.
    if permission == PERMISSION_EDIT and not can_change_tasks_of(db, actor, owner.id):
        raise ActionNotAllowed(
            f"You can let others change {owner.email}'s tasks only if you can change them"
        )


def check_revoke(actor: User, viewer: User, owner: User) -> None:
    # Reducing access is always within an actor's powers over that user.
    ensure_can_manage(actor, viewer)
    ensure_same_business(actor, owner)


def check_transfer_leadership(actor: User, new_leader: User) -> None:
    # The one action on oneself: the leader steps down to admin.
    if not actor.is_leader:
        raise ActionNotAllowed("Only the leader can transfer leadership")
    ensure_same_business(actor, new_leader)
