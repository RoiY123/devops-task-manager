"""Endpoints for the management page; each works only in the caller's own business."""
from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.backend.accounts import UserListing, list_task_grants, list_users
from app.backend.database import get_db
from app.backend.models import User
from app.backend.permissions import can_manage, check_can_view_management
from app.backend.schemas import GrantSummary, Me, UserSummary
from app.backend.security import get_current_user


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


@router.get("/me", response_model=Me)
def get_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = next(row for row in users_of(db, current_user) if row.user_id == current_user.id)
    return Me(
        **summary(row).model_dump(),
        business_slug=current_user.business.slug,
        can_manage=can_manage(current_user),
    )


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
