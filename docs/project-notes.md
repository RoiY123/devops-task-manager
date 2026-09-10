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
- Node Exporter
- Alertmanager

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
- Docker image publishing to GitHub Container Registry (GHCR)
- AWS EC2 deployment
- Nginx reverse proxy
- HTTPS with Let's Encrypt
- Automated certificate renewal
- Production deployment documentation
- Amazon RDS PostgreSQL deployment
- Private EC2-to-RDS connectivity
- TLS-encrypted production database connection
- Production database migration from Docker to RDS
- Infrastructure as Code with Terraform
- Remote Terraform state in Amazon S3
- Terraform-managed EC2, Elastic IP, security groups, RDS, and DB subnet group
- Existing AWS VPC and subnets referenced through Terraform data sources
- FastAPI Prometheus instrumentation
- Prometheus metrics endpoint
- Production Prometheus monitoring
- Dedicated monitoring EC2 instance
- Node Exporter host monitoring
- Grafana application and host monitoring dashboards
- Dashboard provisioning from version-controlled JSON
- Prometheus alert rules
- Alertmanager notification routing
- Gmail firing and resolved alert notifications
- Automated Continuous Deployment with GitHub Actions
- AWS authentication from GitHub Actions using OIDC
- Remote deployments to EC2 using AWS Systems Manager
- Immutable application deployments using Git commit SHA image tags
- Production configuration and secrets loaded from AWS Systems Manager Parameter Store
- Automated Alembic migrations during application deployment
- Automated monitoring configuration deployment and readiness verification

Current milestone:
- Continuous Deployment automation completed

Next milestone:
- Project hardening and final polish

---

## Architecture

Current application:

```text
Developer Push to main
        ↓
GitHub Actions
        ↓
      Test
        ↓
Build and Publish Immutable Image to GHCR
        ↓
AWS OIDC Authentication
        ↓
AWS Systems Manager
        ↓
Application EC2
        ↓
Generate Production Configuration
        ↓
Run Alembic Migrations
        ↓
Docker Compose
        ↓
Nginx (HTTPS)
        ↓
     FastAPI
        ↓
AWS RDS PostgreSQL
```

Local development:

```text
  Docker Compose
        ↓
  FastAPI Container
        ↓
  Authentication (JWT)
        ↓
  SQLAlchemy ORM
        ↓
  PostgreSQL Container
        ↓
  Named Docker Volume
```

Infrastructure management:

```text
  Terraform
      ↓
  Remote State (Amazon S3)
      ↓
  AWS Infrastructure:
    ├─ Existing Default VPC and Subnets (data sources)
    ├─ EC2 Security Groups
    ├─ EC2 Application and Monitoring Servers
    ├─ Elastic IP
    ├─ RDS Security Group
    ├─ RDS DB Subnet Group
    └─ Amazon RDS PostgreSQL
```

Production monitoring:

```text
  GitHub Actions
      ↓
  AWS Systems Manager
      ↓
  Monitoring EC2
      ↓
  Generate Runtime Configuration
      ↓
  Docker Compose
      ↓
  Prometheus:
    ├─ FastAPI metrics on application EC2
    ├─ Node Exporter metrics on application EC2
    └─ Prometheus self-monitoring
      ↓
  Grafana
      ↓
  Provisioned Application and Host dashboards

  Alerting:

  Prometheus Alert Rules
        ↓
  Alertmanager
        ↓
  Gmail Notifications
        ↓
  Firing and Resolved Alerts
```

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

### Managed Production Database

Decision:

Use Amazon RDS for the production PostgreSQL database while retaining a containerized PostgreSQL service for local development.

Keep RDS privately accessible inside the VPC and allow port `5432` only from the EC2 security group. Require TLS for the application database connection and apply schema changes using Alembic migrations.

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

Store application configuration and secrets using environment variables.

Commit environment-specific templates (`.env.example`, `.env.docker.example`, `.env.prod.example`, and `.env.monitoring.example`) while excluding real environment files from version control.

For production, store sensitive and runtime configuration in AWS Systems Manager Parameter Store and generate `.env.prod` and `.env.monitoring` automatically during deployment.

Status:
Accepted

---

### Containerization

Decision:

Use Docker Compose to orchestrate the FastAPI application and PostgreSQL database.

Persist database data using a named Docker volume, isolate services on a dedicated Docker network, and execute database migrations through Alembic inside Docker containers.

Use Docker Compose for local development with bind mounts and automatic application reloads.

Keep the Dockerfile production-oriented while allowing Compose to override runtime behavior for development.

Use a separate `compose.prod.yml` configuration for production, with prebuilt GHCR images, the FastAPI application, Nginx, Node Exporter, and Certbot, while using Amazon RDS for PostgreSQL.

Status:
Accepted

---

### Testing Strategy

Decision:

Use integration tests with pytest, FastAPI's TestClient, and a dedicated PostgreSQL test database.
Each test runs inside its own database transaction, which is rolled back after execution to ensure complete isolation.
Authentication is performed through the application's real login endpoint, and reusable pytest fixtures provide authenticated users and shared test setup.

Status:
Accepted

---

### Continuous Integration

Decision:

Use GitHub Actions to validate every code change in a clean environment.
Each workflow provisions a temporary PostgreSQL database, applies Alembic migrations, and executes the full integration test suite before changes are considered ready for deployment.

Status:
Accepted

---

### Continuous Deployment

Decision:

Use GitHub Actions to deploy automatically after successful CI on the `main` branch.

Authenticate GitHub Actions to AWS using OIDC instead of long-lived AWS credentials.
Use AWS Systems Manager to run deployment commands on the application and monitoring EC2 instances without exposing deployment SSH credentials.

Deploy immutable GHCR application images tagged with the Git commit SHA.
Generate production runtime configuration from AWS Systems Manager Parameter Store during deployment.

Run Alembic migrations using the exact application image being deployed before reconciling the API service.
Deploy monitoring configuration automatically and verify Prometheus, Grafana, and Alertmanager readiness before considering the deployment successful.

Status:
Accepted

---

### Production Deployment

Decision:

Use Docker Compose to orchestrate production services on AWS EC2.
Terminate HTTPS with Nginx, issue TLS certificates using Let's Encrypt, and automate certificate renewal through Certbot and cron.
Deploy prebuilt application images from GitHub Container Registry instead of building directly on the production server.

Status:
Accepted

---

### Infrastructure as Code

Decision:

Use Terraform to manage project-specific AWS infrastructure, including EC2, Elastic IPs, security groups, the RDS DB subnet group, and the production RDS PostgreSQL instance.

Store the main Terraform state remotely in a private Amazon S3 bucket with versioning, encryption, public-access blocking, and state locking.

Treat the AWS default VPC and default subnets as existing shared infrastructure and reference them using Terraform data sources rather than importing their lifecycle into the project's Terraform state.

Adopt existing production resources incrementally using Terraform import and require a reviewed, non-destructive plan before applying infrastructure changes.

Status:
Accepted

---

### Monitoring and Alerting

Decision:

Use Prometheus for application and infrastructure metrics, Grafana for visualization, Node Exporter for Linux host metrics, and Alertmanager for alert routing and notification delivery.

Run Prometheus, Grafana, and Alertmanager on a dedicated monitoring EC2 instance so monitoring remains independent from the application host during application failures.

Manage Grafana dashboards through version-controlled provisioning files rather than direct production UI changes.

Use Prometheus alert rules for application availability, host monitoring availability, CPU, memory, and filesystem usage. Route firing and resolved notifications through Alertmanager using Gmail SMTP.

Store monitoring secrets in AWS Systems Manager Parameter Store and generate the ignored `.env.monitoring` runtime file during deployment. Keep the Alertmanager configuration structure in a tracked template and generate the secret-bearing runtime configuration on the monitoring host.

Status:
Accepted

## Next Session

Begin project hardening and final polish.

Topics:

- Review security and operational hardening
- Review documentation and architecture consistency
- Final project cleanup
- Prepare the repository for portfolio presentation