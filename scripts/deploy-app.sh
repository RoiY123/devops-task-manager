#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/task-manager}"
REPO_RAW_URL="${REPO_RAW_URL:-https://raw.githubusercontent.com/RoiY123/devops-task-manager}"

if [[ -z "${COMMIT_SHA:-}" ]]; then
  echo "ERROR: COMMIT_SHA is not set."
  exit 1
fi

if [[ -z "${IMAGE_TAG:-}" ]]; then
  echo "ERROR: IMAGE_TAG is not set."
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "Deploying commit: $COMMIT_SHA"
echo "Deploying image tag: $IMAGE_TAG"

# Ensure the expected runtime directory structure exists.
mkdir -p \
  "$PROJECT_DIR/docker/nginx" \
  "$PROJECT_DIR/scripts"

chown ubuntu:ubuntu \
  "$PROJECT_DIR/docker" \
  "$PROJECT_DIR/docker/nginx" \
  "$PROJECT_DIR/scripts"

chmod 0755 \
  "$PROJECT_DIR/docker" \
  "$PROJECT_DIR/docker/nginx" \
  "$PROJECT_DIR/scripts"

# Download tracked production files from the exact Git commit being deployed.
curl -fSL \
  "$REPO_RAW_URL/$COMMIT_SHA/compose.prod.yml" \
  -o "$TMP_DIR/compose.prod.yml"

curl -fSL \
  "$REPO_RAW_URL/$COMMIT_SHA/docker/nginx/default.conf" \
  -o "$TMP_DIR/default.conf"

curl -fSL \
  "$REPO_RAW_URL/$COMMIT_SHA/scripts/renew-certificates.sh" \
  -o "$TMP_DIR/renew-certificates.sh"

# Install tracked runtime files with explicit ownership and permissions.
install -o ubuntu -g ubuntu -m 0644 \
  "$TMP_DIR/compose.prod.yml" \
  "$PROJECT_DIR/compose.prod.yml"

# Preserve the currently working Nginx configuration before replacing it.
if [[ -f "$PROJECT_DIR/docker/nginx/default.conf" ]]; then
  cp \
    "$PROJECT_DIR/docker/nginx/default.conf" \
    "$TMP_DIR/default.conf.previous"
fi

install -o ubuntu -g ubuntu -m 0644 \
  "$TMP_DIR/default.conf" \
  "$PROJECT_DIR/docker/nginx/default.conf"

install -o ubuntu -g ubuntu -m 0755 \
  "$TMP_DIR/renew-certificates.sh" \
  "$PROJECT_DIR/scripts/renew-certificates.sh"

cd "$PROJECT_DIR"

# Validate the new Nginx configuration before loading it.
if ! docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  exec -T nginx nginx -t
then
  if [[ -f "$TMP_DIR/default.conf.previous" ]]; then
    install -o ubuntu -g ubuntu -m 0644 \
      "$TMP_DIR/default.conf.previous" \
      "$PROJECT_DIR/docker/nginx/default.conf"

    echo "Previous Nginx configuration restored."
  else
    rm -f "$PROJECT_DIR/docker/nginx/default.conf"

    echo "Invalid Nginx configuration removed."
  fi

  echo "ERROR: Nginx configuration validation failed."
  exit 1
fi

# Load the validated configuration without recreating the Nginx container.
docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  exec -T nginx nginx -s reload

# Pull the images required by the long-running production services.
IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  pull \
  api \
  nginx \
  node-exporter

# Reconcile the long-running production services with compose.prod.yml.
IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  up -d \
  api \
  nginx \
  node-exporter

echo "Application deployment completed successfully."