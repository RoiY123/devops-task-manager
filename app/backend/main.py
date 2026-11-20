import os
import time

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.backend.database import check_database_connection
from app.backend.management import router as management_router
from app.backend.permissions import ActionNotAllowed
from app.backend.routes import router
from app.backend.monitoring import (
    DATABASE_CONNECTION_UP,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_IN_PROGRESS,
    HTTP_REQUESTS_TOTAL,
)


ENABLE_DOCS = os.getenv("ENABLE_DOCS", "true").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_database_connection()
    yield


app = FastAPI(
    title="DevOps Task Manager API",
    lifespan=lifespan,
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)


app.include_router(router)
app.include_router(management_router)


@app.exception_handler(ActionNotAllowed)
async def action_not_allowed(request: Request, error: ActionNotAllowed) -> JSONResponse:
    # Refused management actions become 403 with their reason, from any endpoint.
    return JSONResponse(status_code=403, content={"detail": str(error)})


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
    }

@app.middleware("http")
async def collect_http_metrics(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
    
    HTTP_REQUESTS_IN_PROGRESS.inc()

    start_time = time.perf_counter()

    try:
        response = await call_next(request)

        route = request.scope.get("route")

        if route is not None:
            endpoint = route.path
        elif response.status_code == 404:
            endpoint = "unmatched"
        else:
            endpoint = request.url.path

        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            endpoint=endpoint,
            status_code=response.status_code,
        ).inc()

        duration = time.perf_counter() - start_time

        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method,
            endpoint=endpoint,
        ).observe(duration)

        return response

    finally:
        HTTP_REQUESTS_IN_PROGRESS.dec()

@app.get("/metrics", include_in_schema=False)
def metrics():
    try:
        check_database_connection()
        DATABASE_CONNECTION_UP.set(1)
    except Exception:
        DATABASE_CONNECTION_UP.set(0)

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )