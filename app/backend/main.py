from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.backend.database import check_database_connection
from app.backend.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_database_connection()
    yield


app = FastAPI(
    title="DevOps Task Manager API",
    lifespan=lifespan,
)


app.include_router(router)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
    }