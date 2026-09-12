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
  '/docker/nginx/' \
  '/scripts/renew-certificates.sh'

# Check out the exact commit that triggered the deployment.
git checkout "$COMMIT_SHA"

# Prepare runtime directories
install -d -o ubuntu -g ubuntu -m 0755 \
  "$PROJECT_DIR" \
  "$PROJECT_DIR/docker" \
  "$PROJECT_DIR/scripts"

# Detect tracked configuration changes
NGINX_RELOAD_NEEDED=false
COMPOSE_CHANGED=false

# Detect whether compose.prod.yml changed.
if [[ ! -f "$PROJECT_DIR/compose.prod.yml" ]] \
  || ! cmp -s \
    "$STAGING_DIR/compose.prod.yml" \
    "$PROJECT_DIR/compose.prod.yml"; then
  COMPOSE_CHANGED=true
fi

# Detect actual Nginx file-content changes.
if [[ -n "$(rsync -rcni \
  --delete \
  "$STAGING_DIR/docker/nginx/" \
  "$PROJECT_DIR/docker/nginx/")" ]]; then
  NGINX_RELOAD_NEEDED=true
fi

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

# Validate Nginx configuration
# Validate when either the Nginx files or Compose definition changed.
if [[ "$NGINX_RELOAD_NEEDED" == true ]] \
  || [[ "$COMPOSE_CHANGED" == true ]]; then

  echo "Validating Nginx configuration..."

  if ! docker compose \
    --env-file .env.prod \
    -f compose.prod.yml \
    run --rm --no-deps nginx nginx -t
  then
    echo "Nginx configuration validation failed. Restoring previous configuration..."

    if [[ -d "$TMP_DIR/nginx.previous" ]]; then
      rm -rf "$PROJECT_DIR/docker/nginx"

      cp -a \
        "$TMP_DIR/nginx.previous" \
        "$PROJECT_DIR/docker/nginx"
    else
      rm -rf "$PROJECT_DIR/docker/nginx"

      install -d -o ubuntu -g ubuntu -m 0755 \
        "$PROJECT_DIR/docker/nginx"
    fi

    if [[ -f "$TMP_DIR/compose.prod.yml.previous" ]]; then
      cp -a \
        "$TMP_DIR/compose.prod.yml.previous" \
        "$PROJECT_DIR/compose.prod.yml"
    else
      rm -f "$PROJECT_DIR/compose.prod.yml"
    fi

    echo "Previous production configuration restored."
    echo "ERROR: Nginx configuration validation failed."
    exit 1
  fi
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

# Capture current Nginx container
NGINX_CONTAINER_BEFORE="$(
  docker compose \
    --env-file .env.prod \
    -f compose.prod.yml \
    ps -q nginx
)"

# Pull remaining service images
IMAGE_TAG="$IMAGE_TAG" docker compose \
  --env-file .env.prod \
  -f compose.prod.yml \
  pull \
  nginx \
  node-exporter

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

# Reload Nginx only when required
if [[ "$NGINX_RELOAD_NEEDED" == true ]] \
  && [[ -n "$NGINX_CONTAINER_BEFORE" ]] \
  && [[ "$NGINX_CONTAINER_BEFORE" == "$NGINX_CONTAINER_AFTER" ]]; then

  echo "Nginx configuration changed. Reloading Nginx..."

  docker compose \
    --env-file .env.prod \
    -f compose.prod.yml \
    exec -T nginx nginx -s reload
fi

# Docker image cleanup
echo "Docker disk usage before image cleanup:"
docker system df

docker image prune -af

echo "Docker disk usage after image cleanup:"
docker system df

echo "Application deployment completed successfully."