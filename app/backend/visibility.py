"""Who may see and change which tasks.

Every rule stays inside the user's own business.
"""
from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from app.backend.models import ROLE_ADMIN, Task, TaskGrant, User


def visible_tasks(user: User) -> ColumnElement[bool]:
    """A filter matching the tasks the user may see."""
    if user.sees_all_tasks:
        return Task.business_id == user.business_id

    granted_owners = select(TaskGrant.owner_id).where(TaskGrant.viewer_id == user.id)

    # Grants never cross businesses (their foreign keys ensure it);
    # the business check keeps that true here even if a grant rule is ever loosened.
    return (Task.business_id == user.business_id) & or_(
        Task.owner_id == user.id,
        Task.owner_id.in_(granted_owners),
    )


def get_visible_task(db: Session, user: User, task_id: int) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, visible_tasks(user)))

    # Tasks the user may not see are reported as missing, revealing nothing.
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    return task


def ensure_can_change(user: User, task: Task) -> None:
    """Owners change their tasks; admins change any task they can see."""
    if task.owner_id != user.id and user.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to change this task",
        )
