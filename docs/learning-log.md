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

## Day 6

Learned:
- Implemented route protection using FastAPI dependencies and JWT authentication.
- Understood the difference between authentication (identity) and authorization (permissions).
- Learned how resource ownership is enforced by combining the authenticated user's ID with SQLAlchemy queries.
- Added a one-to-many relationship between `User` and `Task` using SQLAlchemy relationships and foreign keys.
- Learned why APIs often return `404 Not Found` instead of `403 Forbidden` when users attempt to access resources they do not own.
- Understood why application code and database migrations must remain synchronized during deployments.
- Moved application configuration completely to environment variables.
- Learned the purpose of a `.env.example` file and why real secrets should never be committed to Git.

Built:
- Authentication dependency (`get_current_user`) for protected endpoints.
- Task ownership using `owner_id` and SQLAlchemy relationships.
- Authorization for all task CRUD operations.
- Environment-based configuration for the database connection and JWT settings.
- `.env.example` template for project setup.

Git:
feat: implement user authorization and task ownership

## Day 7

Learned:
- Docker Compose architecture and how multiple services are managed as a single application.
- The difference between Docker images, containers, networks, and volumes.
- How Docker Compose creates an isolated network and allows services to communicate using service names (e.g., `postgres`) instead of IP addresses.
- The purpose of Docker health checks and how `depends_on` with `condition: service_healthy` controls startup order.
- How Alembic migrations are executed inside a temporary Docker container using `docker compose run --rm`.
- Why the `alembic_version` table tracks the current database schema version instead of inspecting the database structure.
- The difference between `docker compose stop`, `start`, `up`, and `down`, and how volumes preserve PostgreSQL data across container recreation.
- The role of environment-specific configuration files (`.env`, `.env.docker`, and their example templates).
- How bind mounts allow containers to use source code directly from the host machine.
- Basic Docker debugging techniques using `docker compose ps`, `logs`, `exec`, `inspect`, and `stats`.

Built:
- Docker Compose configuration for the FastAPI application and PostgreSQL database.
- PostgreSQL service with persistent storage using a named Docker volume.
- Docker health check for PostgreSQL using `pg_isready`.
- Containerized Alembic migration workflow.
- Fully containerized FastAPI application communicating with PostgreSQL through the Docker network.
- Development Docker workflow with bind mounts and automatic code reloading.
- Improved local development experience without rebuilding the image after Python code changes.

Git:
feat: improve Docker development workflow

## Day 8

Learned:
- The difference between unit tests and integration tests.
- How `pytest` fixtures reduce duplicated setup code.
- How `conftest.py` provides shared fixtures across the test suite.
- How FastAPI dependency overrides allow tests to replace production database sessions.
- How transaction rollback keeps the test database isolated between test runs.
- How factory fixtures can generate multiple authenticated users without duplicating code.
- Why integration tests should authenticate through the real API instead of bypassing the login endpoint.
- How to test authentication, authorization, and resource ownership from a real client's perspective.
- Why APIs often return `404 Not Found` instead of `403 Forbidden` for resources owned by other users to prevent information disclosure.

Built:
- Isolated PostgreSQL test database.
- Shared pytest fixtures for the test client and database session.
- Authentication header factory fixture for reusable authenticated requests.
- Integration test suite covering health checks, user registration, login, protected endpoints, task creation, and task ownership.
- Automated verification that users cannot view, modify, or delete resources owned by other users.

Git:
test: add integration test suite for authentication and task ownership

## Day 9

Learned:
- The purpose of Continuous Integration (CI) and how it differs from Continuous Deployment (CD).
- The structure of a GitHub Actions workflow (`name`, `on`, `jobs`, `steps`, `services`, and `env`).
- How GitHub Actions creates a clean Ubuntu runner for every workflow execution.
- How service containers allow integration tests to run against a real PostgreSQL database.
- Why Alembic migrations should run in CI before executing integration tests.
- How environment variables are provided to workflows and why their names must match the application's configuration.
- How dependency caching speeds up workflow execution without changing application behavior.
- How to debug GitHub Actions by identifying the first meaningful error in the workflow logs.
- Why CI validates that the application can be built and tested from scratch rather than relying on the local development environment.

Built:
- Complete GitHub Actions CI workflow.
- Automated PostgreSQL service container for testing.
- Automated dependency installation.
- Automated Alembic migration execution.
- Automated integration test execution on every push and pull request.

Git:
ci: add GitHub Actions test workflow

## Day 10

Learned:
- The difference between Continuous Integration (CI) and Continuous Deployment (CD).
- How GitHub Container Registry (GHCR) enables immutable application deployments.
- Production deployment workflow using Docker Compose on an AWS EC2 instance.
- Basic AWS networking concepts, including Security Groups and Elastic IPs.
- How Nginx acts as a reverse proxy and terminates HTTPS connections.
- The TLS certificate lifecycle with Let's Encrypt and Certbot, including HTTP-01 validation and automatic certificate renewal.
- Why production infrastructure should be documented and kept reproducible through version control.

Built:
- Automated Docker image publishing to GitHub Container Registry.
- Production Docker Compose configuration for deployment.
- EC2-hosted deployment using Docker Compose.
- Nginx reverse proxy with HTTPS enabled using Let's Encrypt.
- Automated certificate renewal script with scheduled cron execution.
- Deployment documentation for reproducing the production environment.

Git:
feat: deploy application to AWS with HTTPS and automated certificate renewal

## Day 11

Learned:
- The difference between self-hosted PostgreSQL and a managed Amazon RDS database.
- How RDS DB subnet groups provide placement options across Availability Zones.
- How security-group references restrict PostgreSQL access to approved EC2 resources.
- Why a private RDS instance does not need public internet accessibility.
- How database endpoints and private DNS are used by applications inside a VPC.
- How to test database connectivity in layers: DNS, TCP port, authentication, and SQL queries.
- How Alembic initializes an empty managed database.
- How separating compute from persistent data reduces state on the application server.

Built:
- Private Amazon RDS PostgreSQL instance.
- Dedicated RDS security group allowing PostgreSQL only from the EC2 security group.
- Multi-AZ DB subnet group for RDS placement.
- TLS-encrypted FastAPI connection to RDS.
- RDS schema initialization using Alembic.
- Production Compose configuration without a local PostgreSQL service.
- Verified registration, authentication, and task CRUD operations against RDS.

Git:
feat: migrate production database to Amazon RDS

## Day 12

Learned:
- Terraform fundamentals, including providers, resources, data sources, variables, state, and the plan/apply workflow.
- Why existing AWS resources must be imported before Terraform can manage them safely.
- How to adopt existing infrastructure incrementally and verify each import with a clean Terraform plan.
- The difference between Terraform-managed resources and existing infrastructure referenced through data sources.
- Why shared AWS networking such as the default VPC and default subnets should be referenced rather than unnecessarily owned by the application Terraform state.
- How Terraform resource references create dependency relationships between infrastructure components.
- How lifecycle protection with `prevent_destroy` protects critical infrastructure from accidental replacement or deletion.
- Why remote Terraform state is safer than local state for important infrastructure.
- How to bootstrap an S3 backend separately before migrating the main Terraform state.

Built:
- Terraform AWS provider configuration for the production environment.
- Remote Terraform state backend using Amazon S3 with versioning, encryption, public-access protection, and state locking.
- Terraform management of the EC2 and RDS security groups and their ingress and egress rules.
- Terraform management of the existing EC2 application server and the production Elastic IP and its EC2 association.
- Terraform management of the Amazon RDS PostgreSQL instance and the RDS DB subnet group.
- Production resource tagging with consistent project, environment, management, and resource-name metadata.
- Terraform data sources for the existing default AWS VPC and Availability Zone subnets.
- Dependency references between EC2, security groups, RDS, subnet groups, and shared AWS networking.

Git:
feat: manage RDS database with Terraform
refactor: reference existing AWS networking with data sources