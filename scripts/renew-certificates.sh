#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/task-manager}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.prod}"
LOG_PREFIX="[certificate-renewal]"

echo "$LOG_PREFIX Starting renewal check at $(date --iso-8601=seconds)"

cd "$PROJECT_DIR"

docker compose \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  run --rm certbot renew --quiet

echo "$LOG_PREFIX Renewal check completed successfully"

docker compose \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  exec -T nginx nginx -s reload

echo "$LOG_PREFIX Nginx reloaded successfully"
