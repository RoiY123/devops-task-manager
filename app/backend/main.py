from fastapi import FastAPI

from app.backend.routes import router


app = FastAPI(
    title="DevOps Task Manager API",
)


app.include_router(router)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
    }