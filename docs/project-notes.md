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

Current milestone:
- Authentication

Next milestone:
- Login endpoint
- JWT authentication
- Protected routes
- User ownership for tasks

---

## Architecture

Current application:

FastAPI
↓
SQLAlchemy
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
Use Argon2 (`pwdlib`) for password hashing. Store only hashed passwords in the database and never persist plain-text passwords.

Status:
Accepted

## Next Session

Implement user authentication.

Topics:

- Login endpoint
- Password verification
- JWT access tokens
- Authentication dependencies
- Protected routes
- Associating tasks with authenticated users