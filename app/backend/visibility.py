"""Who may see and change which tasks.

Every rule stays inside the user's own business.
"""
from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.backend.models import ROLE_ADMIN, Task, User


def visible_tasks(user: User) -> ColumnElement[bool]:
    """A filter matching the tasks the user may see."""
    if user.sees_all_tasks:
        return Task.business_id == user.business_id

    return Task.owner_id == user.id


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
