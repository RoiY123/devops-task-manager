from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.models import Business, Task as TaskModel, User
from app.backend.schemas import Task, TaskCreate, TaskUpdate, UserLogin, Token
from app.backend.security import create_access_token, get_current_user, verify_login_password


router = APIRouter()


@router.get("/tasks", response_model=list[Task])
def get_tasks(
    completed: bool | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = select(TaskModel).where(
        TaskModel.owner_id == current_user.id
    )

    if completed is not None:
        statement = statement.where(
            TaskModel.completed == completed
        )

    statement = statement.order_by(TaskModel.id)

    return db.scalars(statement).all()


@router.get("/tasks/{task_id}", response_model=Task)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = select(TaskModel).where(
        TaskModel.id == task_id,
        TaskModel.owner_id == current_user.id,
    )

    task = db.scalar(statement)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )
    
    return task


@router.post("/tasks", response_model=Task, status_code=201)
def create_task(
    task: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    new_task = TaskModel(
        title=task.title,
        completed=False,
        owner_id=current_user.id
    )

    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    return new_task


@router.patch("/tasks/{task_id}", response_model=Task)
def update_task(
    task_id: int,
    updated_task: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = select(TaskModel).where(
        TaskModel.id == task_id,
        TaskModel.owner_id == current_user.id,
    )

    task = db.scalar(statement)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )
    
    if updated_task.title is not None:
        task.title = updated_task.title
    
    if updated_task.completed is not None:
        task.completed = updated_task.completed

    db.commit()
    db.refresh(task)

    return task


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = select(TaskModel).where(
        TaskModel.id == task_id,
        TaskModel.owner_id == current_user.id,
    )

    task = db.scalar(statement)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    db.delete(task)
    db.commit()


# Accounts are created by the operator (app/backend/cli.py);
# there is deliberately no public registration endpoint.
@router.post(
    "/businesses/{slug}/login",
    response_model=Token,
    status_code=status.HTTP_200_OK
)
def login_user(
    slug: str,
    user_data: UserLogin,
    db: Session = Depends(get_db),
):
    # Only users of the named business match, ignoring capitals;
    # an unknown business simply matches nobody.
    users = db.scalars(
        select(User)
        .join(User.business)
        .where(
            Business.slug == slug,
            func.lower(User.email) == user_data.email.strip().lower(),
        )
    ).all()

    # Two matches can only be accounts differing in capitals;
    # refuse rather than guess which one is meant.
    user = users[0] if len(users) == 1 else None

    if not verify_login_password(
        user_data.password,
        user.hashed_password if user else None,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(user_id=user.id)

    return Token(
        access_token=access_token,
        token_type="bearer",
    )