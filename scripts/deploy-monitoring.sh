#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/task-manager-monitoring}"

if [[ -z "${COMMIT_SHA:-}" ]]; then
  echo "ERROR: COMMIT_SHA is not set."
  exit 1
fi

if [[ -z "${APP_PRIVATE_IP:-}" ]]; then
  echo "ERROR: APP_PRIVATE_IP is not set."
  exit 1
fi

export APP_PRIVATE_IP

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

STAGING_DIR="$TMP_DIR/repo"

echo "Deploying monitoring configuration from commit: $COMMIT_SHA"
echo "Using app private IP: $APP_PRIVATE_IP"

# Fetch only the runtime paths needed by the monitoring server.
git clone \
  --no-checkout \
  --filter=blob:none \
  https://github.com/RoiY123/devops-task-manager.git \
  "$STAGING_DIR"

cd "$STAGING_DIR"

git sparse-checkout init --no-cone

git sparse-checkout set \
  --no-cone \
  '/compose.monitoring.prod.yml' \
  '/monitoring/prod/'

# Check out the exact commit that triggered the deployment.
git checkout "$COMMIT_SHA"

# Ensure the top-level runtime directories exist.
install -d -o ubuntu -g ubuntu -m 0755 \
  "$PROJECT_DIR" \
  "$PROJECT_DIR/monitoring/prod" \
  "$PROJECT_DIR/runtime/alertmanager"

install -o ubuntu -g ubuntu -m 0644 \
  "$STAGING_DIR/compose.monitoring.prod.yml" \
  "$PROJECT_DIR/compose.monitoring.prod.yml"

GRAFANA_RESTART_NEEDED=false
PROMETHEUS_RELOAD_NEEDED=false
ALERTMANAGER_RELOAD_NEEDED=false

# Detect Grafana provisioning changes before synchronizing files.
if [[ -n "$(rsync -acni \
  --no-times \
  --delete \
  "$STAGING_DIR/monitoring/prod/grafana/provisioning/" \
  "$PROJECT_DIR/monitoring/prod/grafana/provisioning/")" ]]; then
  GRAFANA_RESTART_NEEDED=true
fi

# Detect Prometheus configuration changes before synchronizing files.
if [[ -n "$(rsync -acni \
  --no-times \
  --delete \
  "$STAGING_DIR/monitoring/prod/prometheus/" \
  "$PROJECT_DIR/monitoring/prod/prometheus/")" ]]; then
  PROMETHEUS_RELOAD_NEEDED=true
fi

# Sync tracked monitoring configuration from the exact Git commit.
rsync -a \
  --checksum \
  --no-times \
  --delete \
  --chown=ubuntu:ubuntu \
  "$STAGING_DIR/monitoring/prod/" \
  "$PROJECT_DIR/monitoring/prod/"

echo "Generating .env.monitoring from Parameter Store..."

ALERT_EMAIL="$(aws ssm get-parameter \
  --region il-central-1 \
  --name "/task-manager/prod/monitoring/ALERT_EMAIL" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text)"

ALERT_SMTP_PASSWORD="$(aws ssm get-parameter \
  --region il-central-1 \
  --name "/task-manager/prod/monitoring/ALERT_SMTP_PASSWORD" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text)"

GRAFANA_ADMIN_PASSWORD="$(aws ssm get-parameter \
  --region il-central-1 \
  --name "/task-manager/prod/monitoring/GRAFANA_ADMIN_PASSWORD" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text)"

{
  printf 'APP_PRIVATE_IP=%s\n' "$APP_PRIVATE_IP"
  printf 'ALERT_EMAIL=%s\n' "$ALERT_EMAIL"
  printf 'ALERT_SMTP_PASSWORD=%s\n' "$ALERT_SMTP_PASSWORD"
  printf 'GRAFANA_ADMIN_PASSWORD=%s\n' "$GRAFANA_ADMIN_PASSWORD"
} > "$TMP_DIR/.env.monitoring"

install -o ubuntu -g ubuntu -m 0600 \
  "$TMP_DIR/.env.monitoring" \
  "$PROJECT_DIR/.env.monitoring"

export ALERT_EMAIL
export ALERT_SMTP_PASSWORD

envsubst '${ALERT_EMAIL} ${ALERT_SMTP_PASSWORD}' \
  < "$PROJECT_DIR/monitoring/prod/alertmanager/alertmanager.template.yml" \
  > "$TMP_DIR/alertmanager.yml"

unset ALERT_EMAIL ALERT_SMTP_PASSWORD GRAFANA_ADMIN_PASSWORD

# Detect changes in the fully rendered Alertmanager configuration.
if [[ ! -f "$PROJECT_DIR/runtime/alertmanager/alertmanager.yml" ]] \
  || ! cmp -s \
    "$TMP_DIR/alertmanager.yml" \
    "$PROJECT_DIR/runtime/alertmanager/alertmanager.yml"; then
  ALERTMANAGER_RELOAD_NEEDED=true
fi

# Validate the generated Alertmanager configuration before installing it.
docker run --rm \
  --entrypoint /bin/amtool \
  -v "$TMP_DIR/alertmanager.yml:/tmp/alertmanager.yml:ro" \
  prom/alertmanager:v0.33.1 \
  check-config /tmp/alertmanager.yml

# Alertmanager v0.33.1 runs as UID/GID 65534 (nobody).
install -o 65534 -g 65534 -m 0600 \
  "$TMP_DIR/alertmanager.yml" \
  "$PROJECT_DIR/runtime/alertmanager/alertmanager.yml"

cd "$PROJECT_DIR"

docker compose \
  --env-file .env.monitoring \
  -f compose.monitoring.prod.yml \
  pull

docker compose \
  --env-file .env.monitoring \
  -f compose.monitoring.prod.yml \
  up -d

# Grafana reads provisioning configuration at startup.
if [[ "$GRAFANA_RESTART_NEEDED" == "true" ]]; then
  echo "Grafana provisioning changed. Restarting Grafana..."

  docker compose \
    --env-file .env.monitoring \
    -f compose.monitoring.prod.yml \
    restart grafana
fi

# Reload Prometheus when its configuration or alert rules changed.
if [[ "$PROMETHEUS_RELOAD_NEEDED" == "true" ]]; then
  echo "Prometheus configuration changed. Reloading Prometheus..."

  docker compose \
    --env-file .env.monitoring \
    -f compose.monitoring.prod.yml \
    kill -s HUP prometheus
fi

# Reload Alertmanager when its rendered configuration changed.
if [[ "$ALERTMANAGER_RELOAD_NEEDED" == "true" ]]; then
  echo "Alertmanager configuration changed. Reloading Alertmanager..."

  docker compose \
    --env-file .env.monitoring \
    -f compose.monitoring.prod.yml \
    kill -s HUP alertmanager
fi

# Verify that all monitoring services become ready after deployment.
for attempt in {1..12}; do
  if curl --fail --silent --show-error --output /dev/null \
      http://127.0.0.1:9090/-/ready \
    && curl --fail --silent --show-error --output /dev/null \
      http://127.0.0.1:3000/api/health \
    && curl --fail --silent --show-error --output /dev/null \
      http://127.0.0.1:9093/-/ready
  then
    echo "Monitoring services are ready."
    echo "Monitoring deployment completed successfully."
    exit 0
  fi

  echo "Monitoring readiness check attempt $attempt failed. Retrying..."
  sleep 5
done

echo "ERROR: Monitoring services did not become ready."
docker compose \
  --env-file .env.monitoring \
  -f compose.monitoring.prod.yml \
  ps

exit 1