# Project Notes

## Goal

Build a production-style DevOps portfolio project.

---

## Technology Stack

Backend:
- FastAPI

Database:
- PostgreSQL

ORM:
- SQLAlchemy

Database Migrations:
- Alembic

Containerization:
- Docker

CI/CD:
- GitHub Actions

Infrastructure:
- Terraform
- AWS

Monitoring:
- Prometheus
- Grafana

---

## Current Progress

Completed:
- FastAPI application
- CRUD API
- PostgreSQL integration
- SQLAlchemy ORM
- Alembic migrations
- User registration
- Password hashing
- Login endpoint
- JWT authentication
- Route protection
- Task ownership
- Authorization for all CRUD operations
- Environment-based configuration

Current milestone:
- Docker development workflow completed

Next milestone:
- CI/CD pipeline with GitHub Actions
- Automated testing
- Docker image build and validation
- Deployment preparation

---

## Architecture

Current application:

Docker Compose:

  FastAPI Container
        ↓
  Authentication (JWT)
        ↓
  SQLAlchemy ORM
        ↓
  PostgreSQL Container
        ↓
  Named Docker Volume

---

## Decisions

### Why FastAPI?

Reason:
- Lightweight
- Excellent documentation
- Strong type support
- Lets us focus on DevOps instead of framework complexity

Status:
Accepted

---

### Git Workflow

- Small logical commits
- Conventional Commits
- Push after every milestone

Status:
Accepted

---

### Database

Decision:
Use PostgreSQL with SQLAlchemy ORM and Alembic.

Status:
Accepted

---

### API Design

- REST API
- JSON responses
- Pydantic request/response models

Status:
Accepted

---

### Authentication

Decision:
Use Argon2 (`pwdlib`) for password hashing and JWT access tokens for stateless authentication.
Store only hashed passwords in the database and include only the authenticated user's ID (`sub`) in the JWT payload.

Status:
Accepted

---

### Configuration

Decision:
Store application configuration and secrets using environment variables. Commit a `.env.example` template while excluding `.env` from version control.

Status:
Accepted

---

### Containerization

Decision:
Use Docker Compose to orchestrate the FastAPI application and PostgreSQL database.
Persist database data using a named Docker volume, isolate services on a dedicated Docker network, and execute database migrations through Alembic inside Docker containers.
Use Docker Compose for local development with bind mounts and automatic application reloads.
Keep the Dockerfile production-oriented while allowing Compose to override runtime behavior for development.
Defer a dedicated production Compose configuration until the deployment phase.

Status:
Accepted

## Next Session

Begin transitioning from application development to DevOps.

Topics:

- Improve the Docker setup
- Build a production-ready container image
- Prepare the application for CI/CD
- Docker Compose improvements
- Deployment strategy