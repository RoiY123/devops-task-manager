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
mkdir -p \
  "$PROJECT_DIR/monitoring/prometheus" \
  "$PROJECT_DIR/monitoring/grafana/provisioning/dashboards" \
  "$PROJECT_DIR/monitoring/grafana/provisioning/datasources" \
  "$PROJECT_DIR/monitoring/grafana/dashboards" \
  "$PROJECT_DIR/monitoring/alertmanager"

chown -R ubuntu:ubuntu \
  "$PROJECT_DIR/monitoring"

find "$PROJECT_DIR/monitoring" -type d -exec chmod 0755 {} \;

# Download tracked monitoring files from the exact Git commit.
curl -fSL \
  "$REPO_RAW_URL/$COMMIT_SHA/compose.monitoring.prod.yml" \
  -o "$TMP_DIR/compose.monitoring.prod.yml"

curl -fSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/prometheus/prometheus.prod.yml" \
  -o "$TMP_DIR/prometheus.prod.yml"

curl -fSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/prometheus/alerts.yml" \
  -o "$TMP_DIR/alerts.yml"

curl -fSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/grafana/provisioning/dashboards/dashboard.yml" \
  -o "$TMP_DIR/dashboard.yml"

curl -fSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/grafana/provisioning/datasources/prometheus.yml" \
  -o "$TMP_DIR/grafana-prometheus.yml"

curl -fSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/grafana/dashboards/task-manager-application-overview.json" \
  -o "$TMP_DIR/task-manager-application-overview.json"

curl -fSL \
  "$REPO_RAW_URL/$COMMIT_SHA/monitoring/grafana/dashboards/task-manager-host-overview.json" \
  -o "$TMP_DIR/task-manager-host-overview.json"

curl -fSL \
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

# Regenerate the runtime Alertmanager configuration from the tracked template.
set -a
source "$PROJECT_DIR/.env.monitoring"
set +a

envsubst \
  < "$PROJECT_DIR/monitoring/alertmanager/alertmanager.template.yml" \
  > "$TMP_DIR/alertmanager.yml"

# Validate the generated Alertmanager configuration before installing it.
docker run --rm \
  --entrypoint /bin/amtool \
  -v "$TMP_DIR/alertmanager.yml:/tmp/alertmanager.yml:ro" \
  prom/alertmanager:v0.33.1 \
  check-config /tmp/alertmanager.yml

install -o ubuntu -g ubuntu -m 0600 \
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

echo "Monitoring deployment completed successfully."