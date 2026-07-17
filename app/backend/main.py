from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()


class TaskCreate(BaseModel):
    title: str

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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/tasks")
def get_tasks(completed: bool | None = None):
    if completed is None:
        return tasks

    return [
        task
        for task in tasks
        if task["completed"] == completed
    ]


@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    for task in tasks:
        if task["id"] == task_id:
            return task

    raise HTTPException(
        status_code=404,
        detail="Task not found"
    )


@app.post("/tasks", status_code=201)
def create_task(task: TaskCreate):
    new_task = {
        "id": len(tasks) + 1,
        "title": task.title,
        "completed": False
    }

    tasks.append(new_task)
    return new_task