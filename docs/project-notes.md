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
- Amazon RDS monitoring in Grafana using the CloudWatch datasource
- Provisioned RDS monitoring dashboard with CPU, memory, storage, connections, I/O, queue depth, and latency metrics
- Grafana-managed RDS alert rules provisioned from version-controlled YAML
- RDS alerts for low storage, high CPU, low freeable memory, high read latency, high write latency, and high disk queue depth
- Grafana-managed alerts forwarded to the existing Prometheus Alertmanager
- SSM-based administration and port forwarding for private monitoring access
- Restricted security-group rules and explicit IMDSv2 configuration
- Non-root application container
- Extended RDS backup retention and required final snapshot on deletion
- Automated replacement-instance prerequisites, TLS bootstrap, and renewal scheduling
- Verified production app replacement with an encrypted root disk, newer pinned AMI, and no SSH key pair
- Verified deployment targeting, HTTPS health, and monitoring after replacement
- Application-to-database connectivity monitoring and alerting
- Pinned dependencies, Dependabot updates, and a dependency-maintenance runbook
- Scheduled GHCR image cleanup
- CI/CD filtering for docs-only pushes to main

Current milestone:
- Production hardening and reproducibility implemented and verified

Next milestone:
- Portfolio presentation and remaining project polish

---

## Architecture

Current application:

```text
Non-docs-only Push to main
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
Metrics and dashboards:

  Prometheus:
    ├─ FastAPI metrics on application EC2
    ├─ Node Exporter metrics on application EC2
    └─ Prometheus self-monitoring
      ↓
   Grafana
    ├─ Provisioned Application dashboard
    └─ Provisioned Host dashboard

  Amazon CloudWatch:
    └─ Amazon RDS metrics
      ↓
   Grafana
    └─ Provisioned RDS dashboard

  Alerting:

  Prometheus Alert Rules
        ↓
  Alertmanager
        ↓
  Gmail Notifications

  Grafana-managed RDS Alert Rules
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

### Business-specific Login

Decision:

Give each business its own login URL using a path segment on the frontend (for example `/b/{slug}/login`) rather than a subdomain, which would require additional DNS and TLS configuration. The URL supplies the business slug; the user enters only email and password.

The API receives the slug explicitly and looks up the user by business and lower-cased email, because the same email may exist in different businesses.<br>
An unknown slug and incorrect credentials return the same generic `401` response. The JWT continues to carry only the user's ID (`sub`); the business is resolved from the database.

Open points: the exact API shape (`POST /businesses/{slug}/login` or a `business_slug` body field) and whether slugs can be renamed.

Status:
Proposed

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

Use GitHub Actions to deploy automatically after successful CI for pushes to `main`, except when all changed files are under `docs/` or are the root `README.md`.<br>
Keep pull-request checks enabled for all changes, including documentation.

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

Install missing host prerequisites through the deployment prerequisite script.<br>
Generate runtime configuration from Parameter Store and bootstrap initial TLS certificates through temporary HTTP-only Nginx configuration when certificate state is absent.

Manage the certificate-renewal schedule in Git and install it during deployment.<br>
Keep renewal, reload status messages and errors in the renewal log while suppressing detailed Docker image-pull progress.

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

### Production Security and Recovery

Decision:

Use AWS Systems Manager for administrative sessions and port forwarding. <br>
Keep inbound SSH closed and bind monitoring web interfaces to loopback.

Allow public HTTP and HTTPS access to the application host.<br>
Restrict application and host metrics access to the monitoring security group, and PostgreSQL access to the application security group.

Require IMDSv2 on both EC2 instances and run the application container as a dedicated non-root user.

Use encrypted root storage and no SSH key pair on the production application instance.<br>
Keep its AMI pinned and review AMI updates as deliberate infrastructure changes.

Retain RDS automated backups for seven days, keep deletion protections enabled, and require a final snapshot for Terraform-managed database deletion.

For planned application replacement, prepare a new instance alongside the old one, retain a temporary recovery option during cutover, and verify deployment, HTTPS, and monitoring before retiring the old instance.

Status:
Accepted

---

### Dependency and Image Maintenance

Decision:

Pin dependency and container-image versions and review updates through Dependabot and the procedure in `docs/dependency-maintenance.md`.

Manage Python dependency inputs and compiled requirements with pip-tools. Check shared dependency versions across development, CI, and production when reviewing updates.

Use scheduled GHCR cleanup and application-host image cleanup to control unused image accumulation.

Status:
Accepted

---

### Monitoring and Alerting

Decision:

Use Prometheus for application and infrastructure metrics, Grafana for visualization, Node Exporter for Linux host metrics, and Alertmanager for alert routing and notification delivery.

Run Prometheus, Grafana, and Alertmanager on a dedicated monitoring EC2 instance so monitoring remains independent from the application host during application failures.

Manage Grafana dashboards through version-controlled provisioning files rather than direct production UI changes.

Use Prometheus alert rules for application availability, application-to-database connectivity, host monitoring availability, CPU, memory, and filesystem usage.<br>
Route firing and resolved notifications through Alertmanager using Gmail SMTP.

Store monitoring secrets in AWS Systems Manager Parameter Store and generate the ignored `.env.monitoring` runtime file during deployment. Keep the Alertmanager configuration structure in a tracked template and generate the secret-bearing runtime configuration on the monitoring host.

Use Amazon CloudWatch as the metrics source for Amazon RDS and configure Grafana's CloudWatch datasource to authenticate through the monitoring EC2 instance role.

Use Grafana-managed alert rules for CloudWatch-backed RDS metrics, provision those rules from version-controlled YAML, and forward them to the existing external Prometheus Alertmanager. Keep Alertmanager as the central notification layer for both Prometheus and Grafana-managed alerts.

Keep monitoring configuration reproducible through Git provisioning.<br> Historical metrics and other volume-backed runtime data require a separate backup or an explicit decision to accept their loss when replacing the monitoring instance.

Status:
Accepted

## Next Session

Complete documentation alignment and review the remaining project work.

Topics:

- Review documentation and architecture consistency
- Complete final repository cleanup and portfolio presentation