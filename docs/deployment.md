# Production Deployment

## Database

Production uses Amazon RDS for PostgreSQL.

The database is private inside the VPC and accepts PostgreSQL traffic only from the application EC2 security group.

RDS storage is encrypted. Automated backups are retained for seven days. AWS deletion protection and Terraform `prevent_destroy` protect the database against accidental deletion.

Terraform-managed deletion requires a final snapshot. These settings provide recovery safeguards; they do not constitute a tested database restore procedure.

Application connectivity is provided through `DATABASE_URL`, which is generated into `.env.prod` during deployment from AWS Systems Manager Parameter Store.

The database must use `UTF8` encoding because business names and task content may contain Hebrew. Confirm `SHOW server_encoding;` returns `UTF8` on any recreated or restored database before connecting the application.

Production migrations run automatically during deployment using the exact application image being deployed:

```bash
docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  run --rm api \
  alembic upgrade head
```

If a migration fails, the deployment stops before the new API container is reconciled.

### Database compatibility and rollback

On an existing deployment, database migrations run while the previous API container is still running. Each migration must therefore remain compatible with that application version.

Before rolling back the application, review migrations applied since the target version and confirm that it supports the current schema. Do not assume an older image is compatible simply because it is available. Record temporary compatibility measures, their removal conditions, and rollback restrictions alongside the relevant migration.

Rolling back an application image does not undo database changes. Prefer restoring a compatible application image or fixing forward. Review potential data loss and stop affected application code before performing a schema downgrade.

Recovery steps are described in [recovery.md](recovery.md).

Migration preservation tests run against disposable PostgreSQL databases in CI. They do not verify the contents or configuration of production RDS.

## Application configuration

Production `.env.prod` is generated automatically on the application EC2 instance during deployment.

Configuration is loaded from AWS Systems Manager Parameter Store and includes:

```env
DATABASE_URL=...
JWT_SECRET_KEY=...
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
ENABLE_DOCS=false
IMAGE_TAG=sha-...
```

The real `.env.prod` file is runtime-only and must not be committed to Git.

Do not edit production configuration directly on EC2. Update the corresponding Parameter Store value and redeploy.

## Application deployment

Production deployments are automated through GitHub Actions.

A push to `main` runs CI, builds the application image, and deploys through AWS Systems Manager using OIDC authentication, unless all changed files are under `docs/` or are the root `README.md` or `CLAUDE.md`.

Pull requests to `main` still run checks for documentation-only changes.
A push containing both documentation and other changes runs the normal
workflow.

The workflow supplies the exact Git commit SHA and its corresponding application image tag.


The workflow discovers running instances using their `Name` tags:

- Application: `task-manager-prod-api`
- Monitoring: `task-manager-prod-monitoring`

Exactly one running instance should match each production name.<br>
The discovered application private IP is passed to monitoring deployment
so Prometheus targets the current application host.

The GitHub deployment IAM policy also restricts SSM commands to the Terraform-managed production instances. Instance names and IAM permissions
must both be aligned when replacing a server.

Deployment performs these steps:

1. Ensure instance prerequisites, including Docker and Compose, are available.
2. Check out runtime configuration from the exact deployment commit.
3. Preserve the previous Compose and Nginx configuration.
4. Install runtime files and generate `.env.prod` from Parameter Store.
5. Retrieve the certificate account email and pull infrastructure images.
6. Ensure certificate files exist, using HTTP bootstrap when necessary.
7. Validate HTTPS configuration early if an API container is already running.
8. Pull the application image, run Alembic migrations, and reconcile the API.
9. Validate HTTPS configuration again before reconciling Nginx.
10. Reconcile Nginx and Node Exporter.
11. Reload Nginx if its existing container was retained.
12. Install the managed certificate-renewal schedule and enable cron.
13. Remove unused Docker images.

GitHub Actions then verifies public HTTPS health before deploying monitoring.

The application deployment checks out these runtime paths:

- `compose.prod.yml`
- `compose.bootstrap.yml`
- `docker/nginx/`
- `docker/nginx-bootstrap/`
- `cron/task-manager-certificates`
- `scripts/renew-certificates.sh`
- `scripts/ensure-certificates.sh`

A retained Nginx container is reloaded to read current configuration and refresh API hostname resolution.<br>
A recreated container loads these at startup.

If HTTPS configuration validation fails, deployment attempts to restore the available previous Compose and Nginx configuration and stops.<br>
Nginx directory contents are restored without replacing the mounted directory.

This is limited configuration recovery, not a complete release rollback:<br>
database migrations, the API image, and `.env.prod` are not rolled back.<br>
Other deployment failures do not automatically invoke this restoration.

The final public health check determines whether the application is reachable through HTTPS.<br>
Container startup and `nginx -t` alone do not
establish application health.

## HTTPS

Nginx terminates HTTPS using a Let's Encrypt certificate covering `roiy.dev` and `api.roiy.dev`.

Nginx forwards HTTPS requests to the API, with two exceptions:
- `/metrics` returns `404`. The API's security group rule restricts only direct access to port 8000, so the proxy must block the path itself; Prometheus scrapes port 8000 directly.
- `/login` is rate-limited per client IP (10 requests per minute with a burst of 5). Excess attempts receive `429` without reaching the API.

Certificate state is stored in the Compose named volume `certbot_certs`.<br>
Certbot writes to this volume, and Nginx mounts it read-only.<br>
The shared `certbot_webroot` volume holds HTTP validation files.

Named volumes survive container recreation. They do not automatically survive replacement of the EC2 disk on which Docker stores them.

Certificate private keys and account state must not be committed to Git.

## Certificate account configuration

Create this Parameter Store parameter in `il-central-1` before deployment:

| Parameter | Type | Purpose |
| --- | --- | --- |
| `/task-manager/prod/app/CERTBOT_EMAIL` | `SecureString` | Let's Encrypt account contact email |

Use the default AWS-managed KMS key, `alias/aws/ssm`.

`deploy-app.sh` retrieves this parameter on every deployment and passes its value to `ensure-certificates.sh` through the `CERTBOT_EMAIL` environment variable.

The email is not written to `.env.prod` and does not belong in `.env.prod.example`. Do not commit its value or print it in deployment logs.

## Automatic certificate bootstrap

`deploy-app.sh` invokes `scripts/ensure-certificates.sh`.

The helper checks the expected certificate and private-key files:

- Both files are nonempty: reuse them without requesting a certificate.
- No certificate state is found for `roiy.dev`: perform initial issuance.
- Incomplete certificate state or an inspection error: stop deployment.

File presence is not a certificate validity or expiration check.

For initial issuance, the helper:

1. Validates the temporary HTTP Nginx configuration.
2. Starts Nginx using `compose.prod.yml` and `compose.bootstrap.yml`.
3. Waits for the temporary HTTP server to respond.
4. Runs Certbot webroot validation for both domain names.
5. Confirms that the certificate files were created.

The temporary configuration serves ACME challenge files and returns HTTP 503 for ordinary requests. It requires neither certificates nor a running API.

After the helper succeeds, deployment starts the API, validates the production HTTPS configuration, and reconciles Nginx using only `compose.prod.yml`.<br>
The changed configuration mount causes bootstrap
Nginx to be replaced with the production configuration.

Both domains must resolve to the intended server, and public port 80 must be reachable for HTTP validation.

If issuance fails, deployment stops. The temporary HTTP server may remain running for diagnosis and retry.<br>
Do not delete existing production certificate volumes to test bootstrap.

## Automatic certificate renewal

Renewal is performed by `scripts/renew-certificates.sh`.<br>
It runs `certbot renew --quiet` and reloads Nginx after a successful check.

The tracked schedule is:

`cron/task-manager-certificates`

Deployment installs it as:

`/etc/cron.d/task-manager-certificates`

The installed file is owned by root with mode `0644`.<br>
Its job runs as `ubuntu` at 02:17 and 14:17 according to the server's cron timezone.

Output is appended to:

`/home/ubuntu/task-manager/certbot-renewal.log`

Deployment removes unused Docker images, so a later renewal run may need to download the Certbot image again.

A successful check does not necessarily mean a certificate was renewed. Certbot renews certificates when they are due.

Update the schedule in Git. Direct edits to the managed file on EC2 are overwritten on the next deployment.<br>
Other cron files and personal crontabs are not modified by deployment.

To verify renewal manually, see **Certificates: verify renewal** in [operator-tasks.md](operator-tasks.md#certificates-verify-renewal).

## Monitoring deployment

Production monitoring runs on a dedicated EC2 instance using:

`compose-monitoring.prod.yml`

Runtime directory:

`/home/ubuntu/task-manager-monitoring`

The deployment is automated through GitHub Actions and AWS Systems Manager.

`.env.monitoring` is generated automatically using:

- the application private IP discovered from AWS
- `ALERT_EMAIL` from Parameter Store
- `ALERT_SMTP_PASSWORD` from Parameter Store
- `GRAFANA_ADMIN_PASSWORD` from Parameter Store

Git-tracked production monitoring configuration is stored under:

`monitoring/prod/`

Grafana provisioning includes:

- Prometheus and CloudWatch data sources
- the external Alertmanager data source
- application, host, and RDS dashboards
- Grafana-managed RDS alert rules

The CloudWatch data source authenticates through the monitoring EC2 instance IAM role and does not require static AWS credentials.

Local-only monitoring configuration is stored under:

`monitoring/local/`

During deployment, the production monitoring configuration is synchronized to the monitoring EC2 from the exact Git commit being deployed.

Prometheus, Grafana, and Alertmanager readiness are checked automatically before the monitoring deployment is considered successful.

### Alertmanager configuration

Tracked template:

`monitoring/prod/alertmanager/alertmanager.template.yml`

Generated runtime configuration:

`/home/ubuntu/task-manager-monitoring/runtime/alertmanager/alertmanager.yml`

The runtime file is generated automatically during deployment from Parameter Store values and contains private SMTP credentials, so it must never be committed to Git.

Alertmanager v0.33.1 runs as UID/GID `65534`, so the generated file is installed with ownership `65534:65534` and mode `0600`.

Alertmanager receives alerts from two sources:

- Prometheus alert rules
- Grafana-managed RDS alert rules

RDS alerts are matched using the `service="rds"` label and use dedicated email formatting. Prometheus alerts continue using the default Alertmanager email template.

The runtime configuration directory is mounted into the Alertmanager container so regenerated configuration files can be reloaded safely.

## Administrative access

Administrative access uses AWS Systems Manager Session Manager.<br> Inbound SSH is closed on both production instances, and no SSH key or monitoring public-IP address is needed.

Interactive sessions are configured to run as `ubuntu`. GitHub Actions deployments use SSM Run Command and execute deployment scripts as root.

Grafana, Prometheus, and Alertmanager bind only to the monitoring host's loopback interface and are reached through SSM port forwarding.

Session, port-forwarding, and other operator commands are in [operator-tasks.md](operator-tasks.md).

## Application instance replacement

The production application instance uses an encrypted root volume, a pinned Ubuntu AMI, IMDSv2, and no SSH key pair. Terraform `prevent_destroy` and AWS termination protection are enabled.

Replacement is a planned maintenance operation. The verified approach is:

1. Create a separate candidate instance through Terraform with the required network access, instance role, encrypted storage, and SSM connectivity.
2. Run the prerequisite script and verify Docker, Compose, AWS access, and connectivity to the existing RDS database.
3. Prepare the deployment script and matching application image from an exact Git commit. Review database migration compatibility before cutover.
4. Prepare the Elastic IP change and a recovery command targeting the old instance. Pause normal deployments during the transition.
5. Move the production Elastic IP to the candidate and deploy. With empty certificate volumes, HTTP validation must reach the candidate before initial certificates can be issued.
6. Verify public HTTPS health, running services, and the renewal schedule.
7. Align Terraform resource tracking, production instance names, and GitHub deployment permissions with the replacement.
8. Run the normal deployment workflow and verify monitoring uses the new private IP, with application and Node Exporter targets reporting `UP`.
9. Retire the old instance after verification, explicitly handling its termination protections and reviewing a destruction plan scoped to it.
10. Confirm production health and a clean Terraform plan, and commit the final infrastructure configuration.

This approach includes downtime between the Elastic IP switch and successful application startup with HTTPS.

The old instance provides a temporary traffic-recovery option while retained. Moving the Elastic IP back does not undo database migrations. Recovery must account for compatibility between the old application and the current schema.

Application data remains in RDS. Local certificate state, logs, and other files on an instance's root disk do not automatically transfer to its replacement.

## Monitoring persistence

Monitoring configuration, dashboards, data sources, and alert rules are provisioned from Git, with secrets supplied through Parameter Store.

Prometheus history, Grafana runtime data, and Alertmanager state reside in Docker volumes on the monitoring instance. Recreating configuration does not restore those volumes.

Before replacing the monitoring instance, back up required runtime data or explicitly accept its loss.

## Verification

The deployment workflow automatically verifies:

- `https://api.roiy.dev/health`
- Prometheus readiness
- Grafana health
- Alertmanager readiness

Manual verification can also include:

- application, host, and RDS dashboards loading in Grafana
- Prometheus targets reporting `UP`
- Prometheus alert rules appearing in Grafana
- provisioned RDS alert rules appearing in Grafana and evaluating normally
- CloudWatch RDS metrics returning data in Grafana
- monitoring interfaces reachable through SSM port forwarding
- Prometheus scraping FastAPI and Node Exporter from the current production application instance, with both targets reporting `UP`
- `database_connection_up` reporting `1`
- after Nginx configuration changes or instance replacement, `https://api.roiy.dev/metrics` returning `404`
- the managed certificate-renewal schedule installed and cron active
- after a normal deployment, `alembic current` matching the intended revision in the deployed image

Verification after a rollback or other manual recovery is described in [recovery.md](recovery.md#verify-after-recovery).