# Learning Log

## Day 1
Learned:
- Client/server architecture
- HTTP request flow
- FastAPI vs Uvicorn
- Virtual environments

Built:
- First FastAPI application
- GET /health endpoint

Git:
feat: initialize FastAPI application with health endpoint

## Day 2
Learned:
- Docker basics (containers vs images)
- Running PostgreSQL with Docker
- SQLAlchemy Engine, Session, and Connection concepts
- Database connection strings
- FastAPI application lifecycle
- Python context managers (`with`)
- FastAPI lifespan (`@asynccontextmanager`)
- Database connection pooling
- Fail-fast application startup

Built:
- Dockerized PostgreSQL development database
- SQLAlchemy database configuration (`database.py`)
- Database startup connectivity check
- FastAPI lifespan integration
- PostgreSQL health verification during application startup

Git:
feat: configure SQLAlchemy database connectivity