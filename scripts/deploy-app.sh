#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/task-manager}"

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

STAGING_DIR="$TMP_DIR/repo"

echo "Deploying commit: $COMMIT_SHA"
echo "Deploying image tag: $IMAGE_TAG"

# Fetch only the runtime paths needed by the application server.
git clone \
  --no-checkout \
  --filter=blob:none \
  https://github.com/RoiY123/devops-task-manager.git \
  "$STAGING_DIR"

cd "$STAGING_DIR"

git sparse-checkout init --no-cone

git sparse-checkout set \
  --no-cone \
  '/compose.prod.yml' \
  '/compose.bootstrap.yml' \
  '/docker/nginx/' \
  '/docker/nginx-bootstrap/' \
  '/cron/task-manager-certificates' \
  '/scripts/renew-certificates.sh' \
  '/scripts/ensure-certificates.sh'

# Check out the exact commit that triggered the deployment.
git checkout "$COMMIT_SHA"

# Prepare runtime directories
install -d -o ubuntu -g ubuntu -m 0755 \
  "$PROJECT_DIR" \
  "$PROJECT_DIR/docker" \
  "$PROJECT_DIR/docker/nginx-bootstrap" \
  "$PROJECT_DIR/scripts"

# Preserve currently deployed configuration
# Keep the existing Compose file in case Nginx validation fails.
if [[ -f "$PROJECT_DIR/compose.prod.yml" ]]; then
  cp -a \
    "$PROJECT_DIR/compose.prod.yml" \
    "$TMP_DIR/compose.prod.yml.previous"
fi

# Keep the existing Nginx configuration tree for rollback.
if [[ -d "$PROJECT_DIR/docker/nginx" ]]; then
  cp -a \
    "$PROJECT_DIR/docker/nginx" \
    "$TMP_DIR/nginx.previous"
fi

# Install tracked runtime files
install -o ubuntu -g ubuntu -m 0644 \
  "$STAGING_DIR/compose.prod.yml" \
  "$PROJECT_DIR/compose.prod.yml"

rsync -a \
  --checksum \
  --no-times \
  --delete \
  --chown=ubuntu:ubuntu \
  "$STAGING_DIR/docker/nginx/" \
  "$PROJECT_DIR/docker/nginx/"

install -o ubuntu -g ubuntu -m 0755 \
  "$STAGING_DIR/scripts/renew-certificates.sh" \
  "$PROJECT_DIR/scripts/renew-certificates.sh"

# Install certificate bootstrap files
install -o ubuntu -g ubuntu -m 0644 \
  "$STAGING_DIR/compose.bootstrap.yml" \
  "$PROJECT_DIR/compose.bootstrap.yml"

install -o ubuntu -g ubuntu -m 0644 \
  "$STAGING_DIR/docker/nginx-bootstrap/default.conf" \
  "$PROJECT_DIR/docker/nginx-bootstrap/default.conf"

install -o ubuntu -g ubuntu -m 0755 \
  "$STAGING_DIR/scripts/ensure-certificates.sh" \
  "$PROJECT_DIR/scripts/ensure-certificates.sh"

# Generate application environment
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

cd "$PROJECT_DIR"

# Retrieve certificate account configuration
echo "Loading certificate account configuration..."

CERTBOT_EMAIL="$(aws ssm get-parameter \
  --region il-central-1 \
  --name "/task-manager/prod/app/CERTBOT_EMAIL" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text)"

# Pull infrastructure images before using them
docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  pull nginx certbot node-exporter

# Ensure certificate files exist
CERTBOT_EMAIL="$CERTBOT_EMAIL" \
PROJECT_DIR="$PROJECT_DIR" \
bash "$PROJECT_DIR/scripts/ensure-certificates.sh"

unset CERTBOT_EMAIL

# Validate HTTPS configuration and restore previous config on failure
validate_nginx_configuration() {

  echo "Validating Nginx configuration..."

  if ! docker compose \
    --env-file .env.prod \
    -f compose.prod.yml \
    run --rm --no-deps nginx nginx -t
  then
    echo "Nginx configuration validation failed. Restoring previous configuration..."

    if [[ -d "$TMP_DIR/nginx.previous" ]]; then
      rsync -a \
        --checksum \
        --delete \
        "$TMP_DIR/nginx.previous/" \
        "$PROJECT_DIR/docker/nginx/"
    else
      echo "No previous Nginx configuration exists to restore."
    fi

    if [[ -f "$TMP_DIR/compose.prod.yml.previous" ]]; then
      cp -a \
        "$TMP_DIR/compose.prod.yml.previous" \
        "$PROJECT_DIR/compose.prod.yml"
    else
      rm -f "$PROJECT_DIR/compose.prod.yml"
    fi

    echo "Configuration restoration completed where previous copies were available."
    echo "ERROR: Nginx configuration validation failed; deployment stopped."
    exit 1
  fi
}

# Preserve early validation on an existing application instance
API_CONTAINER_BEFORE="$(
  docker compose \
    --env-file .env.prod \
    -f compose.prod.yml \
    ps --status running -q api
)"

if [[ -n "$API_CONTAINER_BEFORE" ]]; then
  validate_nginx_configuration
else
  echo "No running API container; HTTPS validation will follow API startup."
fi

# Pull application image
IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  pull api

# Run database migrations
echo "Running database migrations..."

IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  run --rm api \
  alembic upgrade head

echo "Database migrations completed successfully."

# Reconcile API
IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  up -d api

# Validate against the deployed API before activating HTTPS
validate_nginx_configuration

# Capture current Nginx container
NGINX_CONTAINER_BEFORE="$(
  docker compose \
    --env-file .env.prod \
    -f compose.prod.yml \
    ps -q nginx
)"

# Reconcile remaining production services
IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  up -d \
  nginx \
  node-exporter

# Determine whether Nginx was recreated
NGINX_CONTAINER_AFTER="$(
  docker compose \
    --env-file .env.prod \
    -f compose.prod.yml \
    ps -q nginx
)"

# Reload a retained Nginx container to refresh config and API resolution
if [[ -n "$NGINX_CONTAINER_BEFORE" ]] \
  && [[ "$NGINX_CONTAINER_BEFORE" == "$NGINX_CONTAINER_AFTER" ]]; then

  echo "Nginx container was retained. Reloading configuration and API resolution..."

  docker compose \
    --env-file .env.prod \
    -f compose.prod.yml \
    exec -T nginx nginx -s reload
fi

# Ensure the renewal scheduler is available
if ! command -v crontab >/dev/null 2>&1; then
  echo "Installing cron..."
  apt-get update
  apt-get install -y cron
fi

# Install the deployment-managed schedule
install -d -o root -g root -m 0755 /etc/cron.d

install -o root -g root -m 0644 \
  "$STAGING_DIR/cron/task-manager-certificates" \
  /etc/cron.d/task-manager-certificates

systemctl enable --now cron

echo "Deployment-managed certificate renewal schedule installed."

# Docker image cleanup
echo "Docker disk usage before image cleanup:"
docker system df

docker image prune -af

echo "Docker disk usage after image cleanup:"
docker system df

echo "Application deployment completed successfully."