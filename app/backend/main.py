from fastapi import FastAPI
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
def get_tasks():
    return tasks


@app.post("/tasks", status_code=201)
def create_task(task: TaskCreate):
    new_task = {
        "id": len(tasks) + 1,
        "title": task.title,
        "completed": False
    }

    tasks.append(new_task)
    return new_task