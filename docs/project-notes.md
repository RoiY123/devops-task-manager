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
- Operator-created user accounts (public registration closed)
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
- Business tenancy with operator onboarding over SSM
- Migration tests against populated disposable PostgreSQL databases in CI
- Operator user management over SSM: add users, reset passwords, change roles, and remove users in any business
- Full migration-chain test (upgrade, downgrade to base, upgrade) in CI
- Operator business management over SSM: rename business display names, delete empty businesses, and an interactive operator menu
- Least-privilege database user for the application, with migrations under a separate schema-owner URL
- Container access to instance metadata blocked on the application instance
- Business-specific login (`POST /businesses/{slug}/login`) with per-business, case-insensitive email uniqueness
- Manual deployment trigger for `main` with one deployment at a time
- Per-user task access: who sees and who may change other users' tasks (their own, all, or chosen users'), with admins always seeing all and tasks tied to their owner's business by a database constraint
- Task grants between users (view, or view and change), managed by the operator or, through the API, by the leader and admins
- A business leader: exactly one per business, always sees and changes every task, transferable by the operator or the leader
- Management API for the leader and admins: list users and grants, change roles, task access and grants, and transfer leadership, with every permission rule enforced on the server
- Append-only audit log of user, access and business changes (CLI and API), readable by the operator
- Users change their own password; password changes, operator resets and `end-sessions` end existing logins immediately
- Temporary passwords: a password chosen by someone else must be replaced at first login and expires after 7 days; the operator can still set permanent ones
- The leader and admins add users and reset passwords through the API

Current milestone:
- Business roles and user management through the API

Next milestone:
- TBD

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

- Feature branch, pull request to `main`, squash merge
- Small logical commits with Conventional Commits
- Merging to `main` deploys to production unless only documentation changed

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

Use Argon2 (`pwdlib`) for password hashing and signed, short-lived JWT access tokens for authentication.
Store only hashed passwords in the database. The JWT payload holds only the user's ID (`sub`), when the token was issued (`iat`), and when it expires (`exp`).

Each user has an optional cut-off (`users.tokens_valid_after`), and tokens issued before it are refused. Changing your own password, an operator reset and `end-sessions` set it to the current time, so existing logins end on their next request instead of when their tokens expire. The check needs no extra query, because every request already loads the user.

Changing your own password (`PUT /me/password`) requires the current password, so a stolen token alone is not enough. It returns a new token, which keeps the current device logged in.

A password chosen by someone else is temporary (`users.temporary_password_expires_at`): the user must replace it at first login, and it stops working after 7 days. Until it is replaced, every endpoint except `GET /me` and `PUT /me/password` answers `403`; the check is part of the shared login check, so new endpoints get it without extra code. The operator's commands set temporary passwords unless told otherwise (`--permanent`, for example for test accounts). The API sets only temporary ones, generated by the server and returned once, in a response that must not be cached; only their hash is stored.

Known limitations: times are compared in whole seconds, so a token issued earlier in the same second as the cut-off stays valid until it expires. A login that checks the old password just before a reset is saved may still receive a token; `end-sessions` ends it.

Status:
Accepted

---

### Multi-business Tenancy

Decision:

Serve multiple independent businesses from one application and database. Every user account belongs to exactly one business, and business data stays isolated.

Businesses and their first administrators are created by the operator with a command run over SSM; there is no public registration. Users who existed before tenancy were kept in a `legacy` business.

The operator manages users in every business (add, reset password, end logins, change role, remove) and businesses themselves (rename the display name, delete when empty) through the CLI over SSM, so these powers stay behind AWS access. Within their own business, the leader and admins can also manage roles and task access through the API (see Business Management API). An interactive menu in the same CLI offers the same actions; it adds no access path. Commands that take a password or confirm a deletion refuse to run without an interactive terminal. A business that has users has exactly one leader (see Business Leader).

Status:
Accepted

---

### Task Access

Decision:

Who sees and who may change other users' tasks is set per user, not fixed only by role. Admins always see every task in their business; members see their own (the default), all, or their own plus chosen users'. Everyone may change their own tasks; changing another user's task, which includes deleting it, requires editing all (only for users who see all) or an edit grant for that owner (only for tasks they can see). The database enforces that admins see all and that editing all requires seeing all. New admins and members change only their own tasks, and a role change applies the new role's defaults and removes grants. The operator adjusts access through the CLI over SSM; the leader and admins through the API, within the limits in Business Management API.

The planned management page offers own, all, or custom for both seeing and changing. Custom is not stored: it is the user's own tasks plus their grants.

A task the user cannot see returns `404`, so its existence is not revealed; a visible task the user may not change returns `403`.

A grant gives one user access to every task of a chosen owner in the same business: view, or edit (see and change). Grants are one-way, kept within one business by the database, and removed together with either user.

Status:
Accepted

---

### Business Leader

Decision:

Each business with users has exactly one leader, an admin recorded on the business (`businesses.leader_user_id`) rather than a separate role value. One column makes a second leader impossible, a composite foreign key keeps the leader inside the business and refuses deleting them, and versions that predate the leader still treat them as an admin.

The leader always sees and can change every task, so tasks cannot become unmanageable. The leader cannot be demoted or restricted. Leadership moves only by transfer to an admin, and the previous leader becomes an admin with the admin defaults. The leader can be removed only as the business's last user, so a business is deleted by removing its other users, then the leader, then the empty business. The first user of an empty business becomes its leader and must be an admin.

Status:
Accepted

---

### Business Management API

Decision:

The leader and admins manage their own business through API endpoints, which are the server side of the future management page. `GET /me` describes the logged-in user; `GET /business/users` and `GET /business/grants` list the business; the change endpoints mirror the operator CLI. The business always comes from the login, never from the request. Each change finds the users inside the caller's business (`404` otherwise, so other businesses' users are not revealed), checks permissions (`403`), and applies through the same account functions as the CLI, so the data rules are identical (`400`).

No one changes their own role or access, or the leader's; the leader's transfer of leadership is the one exception. Members manage no one. Admins manage only members, may promote or add admins but not demote, and never give more editing than they have. Only the leader changes admins' editing or transfers leadership. Hiding the management page from members is a convenience; the server enforces every rule.

The leader and admins add users (`POST /business/users`) and reset passwords (`POST /business/users/{id}/password-reset`), both with temporary passwords. The leader resets admins' and members' passwords. Admins reset only members' passwords, and only if they edit all tasks: whoever resets a password can log in as that user, so a reset must not give the resetter more access than they already have. No one resets their own password or the leader's through the API; the operator can.

Known limitation: a change sent by an admin at the moment the leader demotes them may still pass its check. Adding users and resetting passwords are not affected: they lock and re-read the business and both users before checking.

Status:
Accepted

---

### Audit Log

Decision:

Every successful change to roles, task access, grants, leadership, users and businesses is recorded in `audit_events`, in the same transaction as the change, so a change is never saved without its record. The actor is the logged-in user for API changes and `operator` for the CLI; who ran an operator command is in AWS's SSM session records. Only real changes are recorded, never refusals or changes that change nothing, and never passwords.

Events copy the business slug and users' emails and have no foreign keys, so the history outlives removed users and deleted businesses. The application's database role may insert and read events but not update or delete them, so even a compromised application cannot rewrite history; only the schema owner can. Changes made while an older application version runs, during a deploy overlap or after a rollback, are not recorded, and downgrading the migration drops the history.

For now only the operator reads the log, through the CLI. Events are kept indefinitely; retention, and the privacy of removed users' emails, are to be decided before launch.

Status:
Accepted

---

### Hebrew-first Product Language

Decision:

Hebrew is the primary user-facing language. Business names and task content must support Hebrew, so every PostgreSQL database must use `UTF8` encoding; check `SHOW server_encoding;` after any database recreation or restore.

Business slugs used in URLs are ASCII-only. The future frontend must use a right-to-left layout and handle mixed Hebrew and English text.

Status:
Accepted

---

### Business-specific Login

Decision:

Give each business its own login URL using a path segment on the frontend (for example `/b/{slug}/login`) rather than a subdomain, which would require additional DNS and TLS configuration. The URL supplies the business slug; the user enters only email and password.

The API receives the slug in the path (`POST /businesses/{slug}/login`) and looks up the user by business and lower-cased email, because the same email may exist in different businesses.<br>
An unknown slug, a user of another business, and incorrect credentials return the same generic `401`, and a login for an unknown email still checks a password so response times do not reveal which accounts exist. The JWT continues to carry only the user's ID (`sub`); the business is resolved from the database.

Slugs are permanent: a renamed slug would break shared login URLs, and a released slug could later lead old links to another business's login page. Before a business goes live, a wrong slug is corrected by deleting the empty business and onboarding it again. Renaming would require redirects and permanently reserved old slugs, built only if a real need appears.

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

Use GitHub Actions to deploy automatically after successful CI for pushes to `main`, except when all changed files are under `docs/` or are the root `README.md` or `CLAUDE.md`.<br>
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

### Schema Changes During Deployment

Decision:

Migrations run while the previous application version is still serving, and that version may be restored afterwards. Keep each migration compatible with it. Record temporary compatibility measures, their removal conditions, and rollback restrictions in the migration's docstring.

Hand-write migrations that move data and name every constraint. Test migrations in CI against disposable PostgreSQL databases, including populated-data upgrades and downgrade round trips. Migration tests refuse to run unless the database host is local (`localhost`, `127.0.0.1`, or the CI `postgres` service), as a guard against accidentally targeting RDS.

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
Restrict application and host metrics access to the monitoring security group, and PostgreSQL access to the application security group.<br>
Block `/metrics` in Nginx, because a security group cannot restrict paths the reverse proxy forwards, and rate-limit business login (`/businesses/{slug}/login`) and password changes (`/me/password`) per client IP, each with its own allowance, to slow password guessing. An attacker using many IP addresses gets the allowance from each.

Require IMDSv2 on both EC2 instances and run the application container as a dedicated non-root user.<br>
Set the application instance's metadata hop limit to 1 so its containers cannot obtain instance credentials; the monitoring instance keeps 2 because Grafana reads CloudWatch through the instance role.

Run the application as a least-privilege database user (`task_manager_app`) that can read and write rows but not change the schema. Run migrations with a separate schema-owner URL (`MIGRATION_DATABASE_URL`), passed only to the migration container.

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

Manage Python dependency inputs and compiled requirements with pip-tools. Keep each pinned version in one file that Dependabot updates; CI and deployment read shared versions from those files instead of repeating them.

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