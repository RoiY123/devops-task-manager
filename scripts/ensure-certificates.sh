#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/task-manager}"
LOG_PREFIX="[certificate-bootstrap]"

cd "$PROJECT_DIR"

COMPOSE=(
  docker compose
  --env-file .env.prod
  -f compose.prod.yml
)

BOOTSTRAP_COMPOSE=(
  "${COMPOSE[@]}"
  -f compose.bootstrap.yml
)

inspect_certificate_state() {
  "${COMPOSE[@]}" run --rm --no-deps -T \
    --entrypoint sh certbot -eu -c '
      cert_dir=/etc/letsencrypt/live/roiy.dev

      if [ -s "$cert_dir/fullchain.pem" ] \
        && [ -s "$cert_dir/privkey.pem" ]; then
        printf "present\n"
      elif [ -e "$cert_dir" ] \
        || [ -L "$cert_dir" ] \
        || [ -e /etc/letsencrypt/archive/roiy.dev ] \
        || [ -e /etc/letsencrypt/renewal/roiy.dev.conf ]; then
        printf "incomplete\n"
      else
        printf "missing\n"
      fi
    '
}

echo "$LOG_PREFIX Checking certificate files..."

CERTIFICATE_STATE="$(inspect_certificate_state)"

case "$CERTIFICATE_STATE" in
  present)
    echo "$LOG_PREFIX Existing certificate files found."
    exit 0
    ;;
  missing)
    echo "$LOG_PREFIX No existing certificate found."
    ;;
  incomplete)
    echo "ERROR: Incomplete certificate state for roiy.dev."
    echo "Inspect the certificate volume before continuing."
    exit 1
    ;;
  *)
    echo "ERROR: Unexpected certificate inspection result."
    exit 1
    ;;
esac

if [[ -z "${CERTBOT_EMAIL:-}" ]]; then
  echo "ERROR: CERTBOT_EMAIL is required for initial issuance."
  exit 1
fi

echo "$LOG_PREFIX Validating bootstrap Nginx configuration..."

"${BOOTSTRAP_COMPOSE[@]}" run --rm --no-deps -T \
  nginx nginx -t

echo "$LOG_PREFIX Starting HTTP bootstrap server..."

"${BOOTSTRAP_COMPOSE[@]}" up -d --no-deps nginx

BOOTSTRAP_READY=false

for attempt in {1..15}; do
  HTTP_STATUS="$(
    curl --silent --output /dev/null \
      --write-out '%{http_code}' \
      --connect-timeout 2 \
      --max-time 3 \
      http://127.0.0.1/ || true
  )"

  if [[ "$HTTP_STATUS" == "503" ]]; then
    BOOTSTRAP_READY=true
    break
  fi

  sleep 2
done

if [[ "$BOOTSTRAP_READY" != true ]]; then
  echo "ERROR: HTTP bootstrap server did not become ready."
  exit 1
fi

echo "$LOG_PREFIX Requesting certificate..."

"${COMPOSE[@]}" run --rm --no-deps -T certbot certonly \
  --non-interactive \
  --webroot \
  --webroot-path=/var/www/certbot \
  --cert-name roiy.dev \
  --email "$CERTBOT_EMAIL" \
  --agree-tos \
  -d roiy.dev \
  -d api.roiy.dev

CERTIFICATE_STATE="$(inspect_certificate_state)"

if [[ "$CERTIFICATE_STATE" != "present" ]]; then
  echo "ERROR: Certificate files are missing after issuance."
  exit 1
fi

echo "$LOG_PREFIX Certificate files are ready for HTTPS."