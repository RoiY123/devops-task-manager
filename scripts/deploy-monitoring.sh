#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/task-manager-monitoring}"
REPO_RAW_URL="${REPO_RAW_URL:-https://raw.githubusercontent.com/RoiY123/devops-task-manager}"

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

echo "Deploying monitoring configuration from commit: $COMMIT_SHA"
echo "Using app private IP: $APP_PRIVATE_IP"

# Ensure the expected runtime directory structure exists.
install -d -o ubuntu -g ubuntu -m 0755 \
  "$PROJECT_DIR" \
  "$PROJECT_DIR/monitoring" \
  "$PROJECT_DIR/monitoring/prometheus" \
  "$PROJECT_DIR/monitoring/grafana" \
  "$PROJECT_DIR/monitoring/grafana/provisioning" \
  "$PROJECT_DIR/monitoring/grafana/provisioning/dashboards" \
  "$PROJECT_DIR/monitoring/grafana/provisioning/datasources" \
  "$PROJECT_DIR/monitoring/grafana/dashboards" \
  "$PROJECT_DIR/monitoring/alertmanager"

# Download tracked monitoring files from the exact Git commit.
curl -fsSL \
  "$REPO_RAW_URL/$COMMIT_SHA/compose.monitoring.prod.yml" \
  -o "$TMP_DIR/compose.monitoring.prod.yml"

curl -fsSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/prometheus/prometheus.prod.yml" \
  -o "$TMP_DIR/prometheus.prod.yml"

curl -fsSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/prometheus/alerts.yml" \
  -o "$TMP_DIR/alerts.yml"

curl -fsSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/grafana/provisioning/dashboards/dashboard.yml" \
  -o "$TMP_DIR/dashboard.yml"

curl -fsSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/grafana/provisioning/datasources/prometheus.yml" \
  -o "$TMP_DIR/grafana-prometheus.yml"

curl -fsSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/grafana/dashboards/task-manager-application-overview.json" \
  -o "$TMP_DIR/task-manager-application-overview.json"

curl -fsSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/grafana/dashboards/task-manager-host-overview.json" \
  -o "$TMP_DIR/task-manager-host-overview.json"

curl -fsSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/alertmanager/alertmanager.template.yml" \
  -o "$TMP_DIR/alertmanager.template.yml"

# Install tracked monitoring files with explicit ownership and permissions.
install -o ubuntu -g ubuntu -m 0644 \
  "$TMP_DIR/compose.monitoring.prod.yml" \
  "$PROJECT_DIR/compose.monitoring.prod.yml"

install -o ubuntu -g ubuntu -m 0644 \
  "$TMP_DIR/prometheus.prod.yml" \
  "$PROJECT_DIR/monitoring/prometheus/prometheus.prod.yml"

install -o ubuntu -g ubuntu -m 0644 \
  "$TMP_DIR/alerts.yml" \
  "$PROJECT_DIR/monitoring/prometheus/alerts.yml"

install -o ubuntu -g ubuntu -m 0644 \
  "$TMP_DIR/dashboard.yml" \
  "$PROJECT_DIR/monitoring/grafana/provisioning/dashboards/dashboard.yml"

install -o ubuntu -g ubuntu -m 0644 \
  "$TMP_DIR/grafana-prometheus.yml" \
  "$PROJECT_DIR/monitoring/grafana/provisioning/datasources/prometheus.yml"

install -o ubuntu -g ubuntu -m 0644 \
  "$TMP_DIR/task-manager-application-overview.json" \
  "$PROJECT_DIR/monitoring/grafana/dashboards/task-manager-application-overview.json"

install -o ubuntu -g ubuntu -m 0644 \
  "$TMP_DIR/task-manager-host-overview.json" \
  "$PROJECT_DIR/monitoring/grafana/dashboards/task-manager-host-overview.json"

install -o ubuntu -g ubuntu -m 0644 \
  "$TMP_DIR/alertmanager.template.yml" \
  "$PROJECT_DIR/monitoring/alertmanager/alertmanager.template.yml"

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
  < "$PROJECT_DIR/monitoring/alertmanager/alertmanager.template.yml" \
  > "$TMP_DIR/alertmanager.yml"

unset ALERT_EMAIL ALERT_SMTP_PASSWORD GRAFANA_ADMIN_PASSWORD

# Validate the generated Alertmanager configuration before installing it.
docker run --rm \
  --entrypoint /bin/amtool \
  -v "$TMP_DIR/alertmanager.yml:/tmp/alertmanager.yml:ro" \
  prom/alertmanager:v0.33.1 \
  check-config /tmp/alertmanager.yml

# Alertmanager v0.33.1 runs as UID/GID 65534 (nobody).
install -o 65534 -g 65534 -m 0600 \
  "$TMP_DIR/alertmanager.yml" \
  "$PROJECT_DIR/monitoring/alertmanager/alertmanager.yml"

cd "$PROJECT_DIR"

docker compose \
  --env-file .env.monitoring \
  -f compose.monitoring.prod.yml \
  pull

docker compose \
  --env-file .env.monitoring \
  -f compose.monitoring.prod.yml \
  up -d

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