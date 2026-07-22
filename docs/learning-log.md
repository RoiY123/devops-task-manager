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

## Day 3
Learned:
- SQLAlchemy ORM models and object mapping
- Alembic database migrations
- SQLAlchemy Unit of Work pattern
- SQLAlchemy dirty tracking
- `db.add()`, `db.commit()`, `db.refresh()`, and `db.delete()`
- `db.scalar()` vs `db.scalars().all()`
- Building SQL queries with `select()`, `where()`, and `order_by()`
- Why PostgreSQL doesn't guarantee row order without `ORDER BY`
- PostgreSQL sequences and why primary key IDs are not reused
- Stateless application architecture and shared database persistence

Built:
- SQLAlchemy `Task` ORM model
- Initial Alembic migration for the `tasks` table
- Persistent CRUD operations backed by PostgreSQL
- Task retrieval with filtering and deterministic ordering
- Database-backed task updates and deletion
- Removed the in-memory task storage completely

Git:
feat: persist tasks in PostgreSQL using SQLAlchemy ORM

## Day 4
Learned:
- Pydantic request vs response schemas
- `ConfigDict(from_attributes=True)` and ORM serialization
- Secure password hashing with Argon2 (`pwdlib`)
- Password verification and the purpose of random salts
- Why passwords should never be stored in plain text
- User registration workflow in a REST API
- Application-level validation vs database unique constraints
- HTTP status codes `201 Created` and `409 Conflict`

Built:
- SQLAlchemy `User` ORM model
- Alembic migration for the `users` table
- Authentication schemas (`UserCreate` and `UserResponse`)
- Password hashing and verification utilities (`security.py`)
- User registration endpoint (`POST /register`)
- Duplicate email validation before user creation

Git:
feat: implement user registration with secure password hashing

## Day 5
Learned:
- JSON Web Token (JWT) authentication workflow
- Difference between authentication and authorization
- JWT structure (Header, Payload, Signature)
- Purpose of the `sub` and `exp` JWT claims
- Why JWTs should contain minimal user information
- Why login endpoints return generic authentication errors to prevent user enumeration
- Loading application secrets from a `.env` file using `python-dotenv`
- Debugging Python package installation issues by inspecting imports instead of changing application code

Built:
- JWT access token generation
- Authentication response schema (`Token`)
- User login endpoint (`POST /login`)
- Login flow with password verification and JWT generation

Git:
feat: implement JWT login authentication