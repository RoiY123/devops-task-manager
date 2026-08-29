# Production Deployment

## Database

Production uses Amazon RDS for PostgreSQL instead of a PostgreSQL container on the EC2 instance.

The RDS database is:

- Deployed privately inside the application VPC
- Accessible on port `5432` only from the EC2 security group
- Configured through `DATABASE_URL` in `.env.prod`
- Initialized and upgraded using Alembic migrations

The production database URL has the following structure:

```text
postgresql+psycopg://USERNAME:PASSWORD@RDS_ENDPOINT:5432/task_manager?sslmode=require
```

Run migrations from the production application image:

```bash
docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  run --rm --no-deps api \
  alembic upgrade head
```

## Application configuration

Production application configuration is stored in `.env.prod` on the application EC2 instance.

Required values include the database connection, JWT settings, and:

```env
ENABLE_DOCS=false
```

The real .env.prod file must not be committed to Git.

After changing application configuration, recreate the API service:

```bash
docker compose --env-file .env.prod -f compose.prod.yml up -d --no-deps api
```

## Application deployment

Production uses the prebuilt API image from GitHub Container Registry.

After a new image is published, update the application manually with:

```bash
docker compose --env-file .env.prod -f compose.prod.yml pull api
docker compose --env-file .env.prod -f compose.prod.yml up -d --no-deps api
```

Run Alembic migrations when the release includes database schema changes.

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

Production monitoring runs separately from the application stack using: `compose.monitoring.prod.yml`

The monitoring EC2 runtime directory is: `/home/ubuntu/task-manager-monitoring`

The monitoring environment file is: `.env.monitoring`

It contains runtime-only values and must not be committed to Git.

Start or update the monitoring stack with:

```bash
docker compose --env-file .env.monitoring -f compose.monitoring.prod.yml up -d
```

Verify the services with:

```bash
docker compose --env-file .env.monitoring -f compose.monitoring.prod.yml ps
```

### Alertmanager configuration

The repository stores the Alertmanager configuration template: `monitoring/alertmanager/alertmanager.template.yml`

The monitoring EC2 uses the generated runtime file: `monitoring/alertmanager/alertmanager.yml`

The runtime file contains private SMTP values and must not be committed to Git.

The required private values are stored in .env.monitoring:

```env
ALERT_EMAIL=...
ALERT_SMTP_PASSWORD=...
```

Generate the runtime configuration after loading .env.monitoring into the shell:

```bash
envsubst '${ALERT_EMAIL} ${ALERT_SMTP_PASSWORD}' \
  < monitoring/alertmanager/alertmanager.template.yml \
  > monitoring/alertmanager/alertmanager.yml
```

Protect the generated file:

```bash
chmod 600 monitoring/alertmanager/alertmanager.yml
```

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


## Verification

After deployment, verify:

- https://roiy.dev/health
- https://api.roiy.dev/health

Both endpoints should return HTTP 200 over HTTPS.

Monitoring verification:

- Prometheus targets for `fastapi`, `node-exporter`, and `prometheus` are `UP`
- Grafana Application and Host Overview dashboards load successfully
- Alertmanager is reachable through the SSH tunnel
- Alert rules appear in Prometheus