from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.models import Task as TaskModel, User
from app.backend.schemas import Task, TaskCreate, TaskUpdate, UserCreate, UserResponse
from app.backend.security import hash_password


router = APIRouter()


@router.get("/tasks", response_model=list[Task])
def get_tasks(
    completed: bool | None = None,
    db: Session = Depends(get_db),    
):
    statement = select(TaskModel).order_by(TaskModel.id)

    if completed is not None:
        statement = statement.where(
            TaskModel.completed == completed
        )

    return db.scalars(statement).all()


@router.get("/tasks/{task_id}", response_model=Task)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
):
    statement = select(TaskModel).where(
        TaskModel.id == task_id
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
):
    new_task = TaskModel(
        title=task.title,
        completed=False,
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
):
    statement = select(TaskModel).where(
        TaskModel.id == task_id
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
):
    statement = select(TaskModel).where(
        TaskModel.id == task_id
    )

    task = db.scalar(statement)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    db.delete(task)
    db.commit()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
):
    existing_user = db.scalar(
        select(User).where(User.email == user_data.email)
    )

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )
    
    user = User(
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user