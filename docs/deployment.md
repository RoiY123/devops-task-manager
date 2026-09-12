# Production Deployment

## Database

Production uses Amazon RDS for PostgreSQL.

The database is private inside the VPC and accepts PostgreSQL traffic only from the application EC2 security group.

Application connectivity is provided through `DATABASE_URL`, which is generated into `.env.prod` during deployment from AWS Systems Manager Parameter Store.

Production migrations run automatically during deployment using the exact application image being deployed:

```bash
docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  run --rm api \
  alembic upgrade head
```

If a migration fails, the deployment stops before the new API container is reconciled.

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

A push to `main` runs:

GitHub Actions
→ AWS authentication with OIDC
→ dynamic EC2 discovery
→ deployment through AWS Systems Manager
→ production configuration generation
→ application image pull
→ Alembic migrations
→ API reconciliation
→ public health verification
→ monitoring deployment

The application is deployed from an immutable GHCR image tagged with the Git commit SHA.

Old unused Docker images are pruned automatically after deployment to prevent disk accumulation.

## HTTPS

HTTPS is terminated by Nginx using certificates issued by Let's Encrypt.

Certificate files are stored in the Docker named volume:

`certbot_certs`

Using a Docker volume ensures that certificates persist across container recreation and are shared between the Certbot and Nginx containers.

The certificates and private keys must not be committed to Git.

## Initial certificate issuance

This command is required only for the initial certificate issuance.
Future renewals are handled automatically by Certbot.
Run this after DNS points to the EC2 Elastic IP and Nginx is available over port 80:

```bash
docker compose --env-file .env.prod -f compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email YOUR_EMAIL \
  --agree-tos \
  --no-eff-email \
  -d roiy.dev \
  -d api.roiy.dev
```

## Test certificate renewal

Verify that future renewals can succeed:

```bash
docker compose --env-file .env.prod -f compose.prod.yml run --rm certbot renew --dry-run
```

A successful dry run confirms that the renewal process is correctly configured without modifying the production certificate.

## Automatic certificate renewal

Certificate renewal is performed by:

`scripts/renew-certificates.sh`

Test it manually:

```bash
./scripts/renew-certificates.sh
```

Install the scheduled job:

```bash
crontab -e
```

```cron
17 2,14 * * * /home/ubuntu/task-manager/scripts/renew-certificates.sh >> /home/ubuntu/task-manager/certbot-renewal.log 2>&1
```

The job runs twice per day.

Certbot renews certificates only when they are close to expiration, so running this job regularly does not request a new certificate every time.

Verify the installed entry:

```bash
crontab -l
```

## Monitoring deployment

Production monitoring runs on a dedicated EC2 instance using:

`compose.monitoring.prod.yml`

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

Local-only monitoring configuration is stored under:

`monitoring/local/`

During deployment, the production monitoring configuration is synchronized to the monitoring EC2 from the exact Git commit being deployed.

Prometheus, Grafana, and Alertmanager readiness are checked automatically before the monitoring deployment is considered successful.

### Alertmanager configuration

The tracked template is:

`monitoring/prod/alertmanager/alertmanager.template.yml`

The generated runtime configuration is:

`/home/ubuntu/task-manager-monitoring/runtime/alertmanager/alertmanager.yml`

The runtime file is generated automatically during deployment from Parameter Store values.

Because Alertmanager v0.33.1 runs as UID/GID `65534`, the generated configuration is installed with ownership `65534:65534` and mode `0600`.

The generated file contains private SMTP values and must not be committed to Git.

## Monitoring access

Grafana is exposed on port `3000` and restricted by the monitoring EC2 security group.

Prometheus and Alertmanager are bound only to the monitoring EC2 loopback interface and should be accessed through SSH tunnels.

Prometheus:

```bash
ssh -i /path/to/key.pem -L 9090:localhost:9090 ubuntu@MONITORING_EC2_PUBLIC_IP
```

Then open: `http://localhost:9090`

Alertmanager:

```bash
ssh -i /path/to/key.pem -L 9093:localhost:9093 ubuntu@MONITORING_EC2_PUBLIC_IP
```

Then open: `http://localhost:9093`

## Manual recovery and troubleshooting

Normal deployments should use GitHub Actions.

For troubleshooting on the application EC2 instance:

```bash
cd /home/ubuntu/task-manager

docker compose --env-file .env.prod -f compose.prod.yml ps
docker compose --env-file .env.prod -f compose.prod.yml logs api
```

Run migrations manually if required:

```bash
IMAGE_TAG="$(grep '^IMAGE_TAG=' .env.prod | cut -d= -f2-)" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  run --rm api \
  alembic upgrade head
```

Reconcile the API manually if required:

```bash
IMAGE_TAG="$(grep '^IMAGE_TAG=' .env.prod | cut -d= -f2-)" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  up -d api
```

For monitoring troubleshooting:

```bash
cd /home/ubuntu/task-manager-monitoring

docker compose \
  --env-file .env.monitoring \
  -f compose.monitoring.prod.yml \
  ps
```

## Verification

The deployment workflow automatically verifies:

- `https://api.roiy.dev/health`
- Prometheus readiness
- Grafana health
- Alertmanager readiness

Manual verification can also include:

- application and host dashboards loading in Grafana
- Prometheus targets reporting `UP`
- Alert rules appearing in Prometheus
- Alertmanager reachable through its SSH tunnel
- `alembic current` matching `alembic heads`