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
- Authentication and authorization completed

Next milestone:
- Docker improvements
- Containerizing the complete application
- CI/CD pipeline with GitHub Actions
- Deployment preparation

---

## Architecture

Current application:

FastAPI
↓
Authentication (JWT)
↓
SQLAlchemy ORM
↓
PostgreSQL

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

## Next Session

Begin transitioning from application development to DevOps.

Topics:

- Improve the Docker setup
- Build a production-ready container image
- Prepare the application for CI/CD
- Docker Compose improvements
- Deployment strategy