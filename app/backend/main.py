from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/tasks")
def get_tasks():
    return [
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