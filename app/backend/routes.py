from fastapi import APIRouter, HTTPException

from app.backend.schemas import Task, TaskCreate, TaskUpdate


router = APIRouter()


tasks = [
    {
        "id": 1,
        "title": "Learn FastAPI",
        "completed": False
    },
    {
        "id": 2,
        "title": "Learn Docker",
        "completed": True
    }
]


@router.get("/tasks", response_model=list[Task])
def get_tasks(completed: bool | None = None):
    if completed is None:
        return tasks

    return [
        task
        for task in tasks
        if task["completed"] == completed
    ]


@router.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: int):
    for task in tasks:
        if task["id"] == task_id:
            return task

    raise HTTPException(
        status_code=404,
        detail="Task not found"
    )


@router.post("/tasks", response_model=Task, status_code=201)
def create_task(task: TaskCreate):
    new_task = {
        "id": len(tasks) + 1,
        "title": task.title,
        "completed": False
    }

    tasks.append(new_task)
    return new_task


@router.patch("/tasks/{task_id}", response_model=Task)
def update_task(task_id: int, task_update: TaskUpdate):
    for task in tasks:
        if task["id"] == task_id:
            if task_update.title is not None:
                task["title"] = task_update.title

            if task_update.completed is not None:
                task["completed"] = task_update.completed

            return task

    raise HTTPException(
        status_code=404,
        detail="Task not found"
    )


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    for task in tasks:
        if task["id"] == task_id:
            tasks.remove(task)
            return
    
    raise HTTPException(
        status_code=404,
        detail="Task not found"
    )