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

echo "Generating .env.prod from Parameter Store..."

DATABASE_URL="$(aws ssm get-parameter \
  --region il-central-1 \
  --name "/task-manager/prod/app/DATABASE_URL" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text)"

JWT_SECRET_KEY="$(aws ssm get-parameter \
  --region il-central-1 \
  --name "/task-manager/prod/app/JWT_SECRET_KEY" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text)"

JWT_ALGORITHM="$(aws ssm get-parameter \
  --region il-central-1 \
  --name "/task-manager/prod/app/JWT_ALGORITHM" \
  --query "Parameter.Value" \
  --output text)"

ACCESS_TOKEN_EXPIRE_MINUTES="$(aws ssm get-parameter \
  --region il-central-1 \
  --name "/task-manager/prod/app/ACCESS_TOKEN_EXPIRE_MINUTES" \
  --query "Parameter.Value" \
  --output text)"

ENABLE_DOCS="$(aws ssm get-parameter \
  --region il-central-1 \
  --name "/task-manager/prod/app/ENABLE_DOCS" \
  --query "Parameter.Value" \
  --output text)"

{
  printf 'DATABASE_URL=%s\n' "$DATABASE_URL"
  printf 'JWT_SECRET_KEY=%s\n' "$JWT_SECRET_KEY"
  printf 'JWT_ALGORITHM=%s\n' "$JWT_ALGORITHM"
  printf 'ACCESS_TOKEN_EXPIRE_MINUTES=%s\n' "$ACCESS_TOKEN_EXPIRE_MINUTES"
  printf 'ENABLE_DOCS=%s\n' "$ENABLE_DOCS"
  printf 'IMAGE_TAG=%s\n' "$IMAGE_TAG"
} > "$TMP_DIR/.env.prod"

install -o ubuntu -g ubuntu -m 0600 \
  "$TMP_DIR/.env.prod" \
  "$PROJECT_DIR/.env.prod"

unset \
  DATABASE_URL \
  JWT_SECRET_KEY \
  JWT_ALGORITHM \
  ACCESS_TOKEN_EXPIRE_MINUTES \
  ENABLE_DOCS

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

# Pull the exact API image before running migrations and reconciling the service.
IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  pull api

# Apply database migrations using the exact application image being deployed.
IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  run --rm api \
  alembic upgrade head

IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  up -d api

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

# Pull the remaining long-running service images.
IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  pull \
  nginx \
  node-exporter

# Reconcile the remaining long-running production services.
IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  up -d \
  nginx \
  node-exporter

# Remove Docker images that are no longer referenced by any container.
echo "Docker disk usage before image cleanup:"
docker system df

docker image prune -af

echo "Docker disk usage after image cleanup:"
docker system df

echo "Application deployment completed successfully."