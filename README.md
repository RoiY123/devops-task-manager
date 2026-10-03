# DevOps Task Manager

A small task-management API with a production-style delivery and operations setup on AWS.

The application supports registration, JWT authentication, and private task lists. The project focuses on the work around the API: automated deployments, infrastructure as code, monitoring, security, and replacing production compute reliably.

## What this project demonstrates

- **Delivery:** GitHub Actions tests changes, publishes commit-tagged images to GHCR, and deploys through AWS Systems Manager using OIDC.
- **Infrastructure:** Terraform manages EC2, networking rules, an Elastic IP, and a private RDS PostgreSQL database.
- **Security:** SSM administration, restricted network access, encrypted storage, a non-root API container, and secrets loaded from Parameter Store.
- **Observability:** Prometheus, Grafana, Node Exporter, CloudWatch RDS metrics, and alerts routed through Alertmanager.
- **Reproducibility:** Automated host prerequisites, initial TLS issuance, and certificate-renewal scheduling—verified through a production app-instance replacement.

## Production architecture

```mermaid
flowchart TD
    Client["API client"] -->|HTTPS| Nginx

    subgraph App["Application EC2"]
        Nginx["Nginx / TLS"] --> API["FastAPI"]
        Node["Node Exporter"]
    end

    API --> RDS["Private RDS PostgreSQL"]

    subgraph Monitoring["Monitoring EC2"]
        Grafana["Grafana"] --> Prometheus["Prometheus"]
    end

    Prometheus -->|Scrapes| API
    Prometheus -->|Scrapes| Node
    Grafana --> CloudWatch["CloudWatch RDS metrics"]
    RDS -->|Publishes metrics| CloudWatch
```

Monitoring interfaces are accessed through SSM port forwarding. Application and host alerts come from Prometheus; RDS alerts are evaluated by Grafana. Both use Alertmanager for email notifications.

## Run locally

Requires Git and Docker with Docker Compose. On Windows, use Docker Desktop and Git Bash for these commands.

```bash
git clone https://github.com/RoiY123/devops-task-manager.git
cd devops-task-manager
cp .env.docker.example .env.docker
```

Edit `.env.docker` and fill in these values, keeping the other example settings:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/task_manager
JWT_SECRET_KEY=replace-with-a-random-local-development-secret
```

The database credentials above match the local Compose configuration. Keep this environment file private and use a random value for the JWT secret.

Build the image, apply migrations, and start the API:

```bash
docker compose build app
docker compose run --rm app alembic upgrade head
docker compose up -d app
```

Compose also starts PostgreSQL and waits for its health check.

- [Interactive API documentation](http://localhost:8000/docs)
- [Health endpoint](http://localhost:8000/health)

Register through `/register`, obtain a token through `/login`, and send it as `Authorization: Bearer <token>` when calling `/tasks`.

Stop the local services with:

```bash
docker compose down
```

The PostgreSQL data volume is retained.

## Delivery and operating boundaries

Pull requests run integration tests against PostgreSQL. Pushes to `main` build and deploy after successful tests, except for docs-only changes.

Production uses a single application instance. Planned instance replacement involves downtime; it is not a highly available deployment. Monitoring configuration is provisioned from Git, while historical metrics and other runtime data require separate backups.

## Explore the project

- [Deployment and operations](docs/deployment.md)
- [Dependency maintenance](docs/dependency-maintenance.md)
- [Architecture decisions and project notes](docs/project-notes.md)
- [Learning milestones](docs/learning-log.md)