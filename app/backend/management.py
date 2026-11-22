"""Endpoints for the management page; each works only in the caller's own business."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.backend.accounts import (
    UserListing,
    change_own_password,
    grant_task_edit,
    grant_task_view,
    list_task_grants,
    list_users,
    revoke_task_edit,
    revoke_task_view,
    set_role,
    set_task_editing,
    set_task_visibility,
    transfer_leadership,
)
from app.backend.database import get_db
from app.backend.models import PERMISSION_EDIT, PERMISSION_VIEW, User
from app.backend.permissions import (
    can_manage,
    check_can_view_management,
    check_grant,
    check_revoke,
    check_set_editing,
    check_set_role,
    check_set_visibility,
    check_transfer_leadership,
)
from app.backend.schemas import (
    GrantSummary,
    LeadershipTransfer,
    LevelChange,
    Me,
    PasswordChange,
    RoleChange,
    Token,
    UserSummary,
)
from app.backend.security import create_access_token, get_current_user


router = APIRouter()


def summary(row: UserListing) -> UserSummary:
    return UserSummary(
        id=row.user_id,
        email=row.email,
        role="leader" if row.is_leader else row.role,
        sees=row.view_level,
        edits=row.edit_level,
    )


def users_of(db: Session, user: User) -> list[UserListing]:
    # The business comes from the caller's login, never from the request.
    return list_users(db, user.business.slug)


def user_in_business(db: Session, actor: User, user_id: int) -> User:
    user = db.get(User, user_id)
    # Another business's user is reported as missing, revealing nothing.
    if user is None or user.business_id != actor.business_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def summary_of(db: Session, user: User) -> UserSummary:
    # Read back after the change, so the page shows what was actually saved.
    return summary(next(row for row in users_of(db, user) if row.user_id == user.id))


@router.get("/me", response_model=Me)
def get_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return Me(
        **summary_of(db, current_user).model_dump(),
        business_slug=current_user.business.slug,
        can_manage=can_manage(current_user),
    )


@router.put("/me/password", response_model=Token)
def change_my_password(
    change: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    change_own_password(
        db,
        user=current_user,
        current_password=change.current_password,
        new_password=change.new_password,
    )
    # Every earlier token is now refused, this device's too; this one replaces it.
    return Token(access_token=create_access_token(user_id=current_user.id), token_type="bearer")


@router.get("/business/users", response_model=list[UserSummary])
def get_business_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_can_view_management(current_user)
    return [summary(row) for row in users_of(db, current_user)]


@router.get("/business/grants", response_model=list[GrantSummary])
def get_business_grants(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_can_view_management(current_user)
    return [
        GrantSummary(**asdict(row))
        for row in list_task_grants(db, current_user.business.slug)
    ]


@router.put("/business/users/{user_id}/role", response_model=UserSummary)
def change_role(
    user_id: int,
    change: RoleChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = user_in_business(db, current_user, user_id)
    check_set_role(current_user, target)
    set_role(
        db,
        business_slug=current_user.business.slug,
        email=target.email,
        role=change.role,
        actor=current_user,
    )
    return summary_of(db, target)


@router.put("/business/users/{user_id}/task-visibility", response_model=UserSummary)
def change_task_visibility(
    user_id: int,
    change: LevelChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = user_in_business(db, current_user, user_id)
    check_set_visibility(current_user, target)
    set_task_visibility(
        db,
        business_slug=current_user.business.slug,
        email=target.email,
        sees_all=change.level == "all",
        actor=current_user,
    )
    return summary_of(db, target)


@router.put("/business/users/{user_id}/task-editing", response_model=UserSummary)
def change_task_editing(
    user_id: int,
    change: LevelChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = user_in_business(db, current_user, user_id)
    edits_all = change.level == "all"
    check_set_editing(current_user, target, edits_all=edits_all)
    set_task_editing(
        db,
        business_slug=current_user.business.slug,
        email=target.email,
        edits_all=edits_all,
        actor=current_user,
    )
    return summary_of(db, target)


def grant_pair(db: Session, actor: User, user_id: int, owner_id: int) -> tuple[User, User]:
    return user_in_business(db, actor, user_id), user_in_business(db, actor, owner_id)


def grant_arguments(actor: User, viewer: User, owner: User) -> dict:
    return {
        "business_slug": actor.business.slug,
        "viewer_email": viewer.email,
        "owner_email": owner.email,
        "actor": actor,
    }


@router.post("/business/users/{user_id}/view-grants/{owner_id}", response_model=UserSummary)
def add_view_grant(
    user_id: int,
    owner_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    viewer, owner = grant_pair(db, current_user, user_id, owner_id)
    check_grant(db, current_user, viewer, owner, permission=PERMISSION_VIEW)
    grant_task_view(db, **grant_arguments(current_user, viewer, owner))
    return summary_of(db, viewer)


@router.post("/business/users/{user_id}/edit-grants/{owner_id}", response_model=UserSummary)
def add_edit_grant(
    user_id: int,
    owner_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    viewer, owner = grant_pair(db, current_user, user_id, owner_id)
    check_grant(db, current_user, viewer, owner, permission=PERMISSION_EDIT)
    grant_task_edit(db, **grant_arguments(current_user, viewer, owner))
    return summary_of(db, viewer)


@router.delete("/business/users/{user_id}/view-grants/{owner_id}", response_model=UserSummary)
def remove_view_grant(
    user_id: int,
    owner_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    viewer, owner = grant_pair(db, current_user, user_id, owner_id)
    check_revoke(current_user, viewer, owner)
    revoke_task_view(db, **grant_arguments(current_user, viewer, owner))
    return summary_of(db, viewer)


@router.delete("/business/users/{user_id}/edit-grants/{owner_id}", response_model=UserSummary)
def remove_edit_grant(
    user_id: int,
    owner_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    viewer, owner = grant_pair(db, current_user, user_id, owner_id)
    check_revoke(current_user, viewer, owner)
    revoke_task_edit(db, **grant_arguments(current_user, viewer, owner))
    return summary_of(db, viewer)


@router.post("/business/leadership", response_model=list[UserSummary])
def change_leadership(
    transfer: LeadershipTransfer,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    new_leader = user_in_business(db, current_user, transfer.user_id)
    check_transfer_leadership(current_user, new_leader)
    transfer_leadership(
        db,
        business_slug=current_user.business.slug,
        email=new_leader.email,
        actor=current_user,
    )
    # The caller was the leader (the check ensures it) and is now an admin.
    return [summary_of(db, new_leader), summary_of(db, current_user)]
