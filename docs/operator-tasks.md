# Operator Tasks

Runbook for routine production operations. How production is built and deployed: [deployment.md](deployment.md). When something is broken: [recovery.md](recovery.md).

Every command block says where to run it and how to paste it:

- **One command:** paste the block as one; lines ending in `\` continue the same command.
- **One line at a time:** run each line and wait for it to finish.
- A command that prompts for input is always alone in its block; type or paste only the answer at the prompt.

## Before you start

Local requirements: AWS CLI, the Session Manager plugin, and credentials for the `task-manager-terraform` profile.

### Open a session on a server

Local PowerShell, from the repository folder; one command. Use `app` for the application instance or `monitoring` for the monitoring instance:

```powershell
./scripts/ssm-shell.ps1 app
```

In the session:

```bash
cd /home/ubuntu/task-manager
```

On the monitoring instance, use `cd /home/ubuntu/task-manager-monitoring` instead.

All application-instance commands below run from `/home/ubuntu/task-manager` and start with `docker compose --env-file .env.prod -f compose.prod.yml`.

## Status and logs

Application instance; one line at a time:

```bash
docker compose --env-file .env.prod -f compose.prod.yml ps
docker compose --env-file .env.prod -f compose.prod.yml logs --tail=50 api
```

Monitoring instance; one command:

```bash
docker compose --env-file .env.monitoring -f compose-monitoring.prod.yml ps
```

## Check the database revision

Application instance; one command:

```bash
docker compose --env-file .env.prod -f compose.prod.yml \
  run --rm --no-deps api alembic current
```

Expected after a normal deployment: the newest revision in `alembic/versions/`, followed by `(head)`. This only reads the revision. After a rollback, use the procedure in [recovery.md](recovery.md#establish-the-current-state) instead.

## Health and login smoke test

Local Git Bash; one command:

```bash
curl -s https://api.roiy.dev/health
```

Expected: `{"status":"healthy"}`.

To check that metrics are not public, one command:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://api.roiy.dev/metrics
```

Expected: `404`. Prometheus scrapes the API directly on port 8000, so this does not affect monitoring.

To check that an account can log in, from the repository folder. This line prompts for the password; run it alone:

```bash
read -rsp "Password: " ADMIN_PASSWORD; echo
```

Then one command, replacing `ADMIN_EMAIL`:

```bash
ADMIN_EMAIL='ADMIN_EMAIL' ADMIN_PASSWORD="$ADMIN_PASSWORD" .venv/Scripts/python -c 'import json, os; print(json.dumps({"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]}))' \
  | curl -s -o /dev/null -w "%{http_code}\n" -H "Content-Type: application/json" --data @- https://api.roiy.dev/login
```

Expected: `200`.<br>
`401` means the email or password is wrong.<br>
`429` means too many recent attempts from your IP; wait a minute and retry.

Then one command:

```bash
unset ADMIN_PASSWORD
```

## Businesses

### Onboard a business

Creates a business and its first administrator. There is no public endpoint for this.

Application instance; one command. It prompts twice for the administrator password; type or paste only the password at each prompt:

```bash
docker compose --env-file .env.prod -f compose.prod.yml \
  exec api python -m app.backend.cli create-business \
  --name "BUSINESS_DISPLAY_NAME" \
  --slug BUSINESS_SLUG \
  --admin-email ADMIN_EMAIL
```

- `--name`: display name; Hebrew is supported.
- `--slug`: part of the business login URL. Lowercase letters, digits and single hyphens, at most 63 characters. Slugs cannot be renamed yet.
- Password: at least 12 characters; the prompt does not display it.
- Do not add `-T`: without an interactive terminal the command refuses to run.

Expected: `Created business 'BUSINESS_SLUG' (id …) with administrator ADMIN_EMAIL (user id …).` On `Error: ...` nothing was created; correct the input and run it again.

Send the password through a secure channel, separately from the login URL and email.

### List businesses and their users

Read-only. Application instance; one command, from the first line to `EOF`:

```bash
docker compose --env-file .env.prod -f compose.prod.yml exec -T api python - <<'EOF'
from sqlalchemy import text
from app.backend.database import SessionLocal

with SessionLocal() as s:
    rows = s.execute(text(
        "SELECT b.slug, b.name, u.id, u.email, u.role "
        "FROM businesses b LEFT JOIN users u ON u.business_id = b.id "
        "ORDER BY b.slug, u.id"
    ))
    for row in rows:
        print(row)
EOF
```

One line per user, as (slug, name, user id, email, role). A business without users shows `None` for the user fields. Terminals may display Hebrew names right-to-left reversed; the stored text is not affected.

## Certificates: verify renewal

Renewal runs automatically; see **Automatic certificate renewal** in [deployment.md](deployment.md#automatic-certificate-renewal).

Inspect the installed schedule and cron service. Application instance; one line at a time:

```bash
sudo cat /etc/cron.d/task-manager-certificates
systemctl is-active cron
systemctl is-enabled cron
```

Test renewal against Let's Encrypt's staging service without replacing production certificates. Application instance; one command:

```bash
docker compose --env-file .env.prod -f compose.prod.yml \
  run --rm --no-deps certbot renew \
  --dry-run \
  --no-random-sleep-on-renew \
  --verbose
```

This skips the randomized delay and prints progress directly. It does not test the Nginx reload or prove cron triggered the job.

To run the real renewal script, including the Nginx reload, as `ubuntu`. Application instance; one command:

```bash
/home/ubuntu/task-manager/scripts/renew-certificates.sh \
  >> /home/ubuntu/task-manager/certbot-renewal.log 2>&1
```

It may take several minutes and print nothing, because output goes to the log and Certbot keeps its randomized delay. It renews certificates if they are due. Then one command:

```bash
tail -n 40 /home/ubuntu/task-manager/certbot-renewal.log
```

Expected: a successful renewal-check message and a successful Nginx-reload message. To confirm scheduled runs, check the log after a scheduled execution.

## Monitoring: open Grafana, Prometheus or Alertmanager

These interfaces listen only on the monitoring instance itself and are reached through SSM port forwarding.

| Service | Port | Local URL |
| --- | --- | --- |
| Grafana | 3000 | http://localhost:3000 |
| Prometheus | 9090 | http://localhost:9090 |
| Alertmanager | 9093 | http://localhost:9093 |

Find the monitoring instance ID. Local Git Bash; one command:

```bash
MONITORING_INSTANCE_ID=$(aws ec2 describe-instances --profile task-manager-terraform --region il-central-1 --filters "Name=tag:Name,Values=task-manager-prod-monitoring" "Name=instance-state-name,Values=running" --query "Reservations[0].Instances[0].InstanceId" --output text); echo "$MONITORING_INSTANCE_ID"
```

Expected: an ID starting with `i-`. Then forward Grafana; one command:

```bash
aws ssm start-session \
  --profile task-manager-terraform \
  --region il-central-1 \
  --target "$MONITORING_INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["3000"],"localPortNumber":["3000"]}'
```

For Prometheus or Alertmanager, replace both port numbers using the table. Keep the terminal open while using the service; use a separate terminal for each tunnel and press Ctrl+C to close it.
