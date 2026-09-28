#!/usr/bin/env bash

set -Eeuo pipefail

echo "Checking instance prerequisites..."

MISSING_PACKAGES=()

command -v curl >/dev/null 2>&1 || MISSING_PACKAGES+=(curl)
command -v git >/dev/null 2>&1 || MISSING_PACKAGES+=(git)
command -v rsync >/dev/null 2>&1 || MISSING_PACKAGES+=(rsync)
command -v envsubst >/dev/null 2>&1 || MISSING_PACKAGES+=(gettext-base)

if (( ${#MISSING_PACKAGES[@]} > 0 )); then
  echo "Installing missing packages: ${MISSING_PACKAGES[*]}"
  apt-get update
  apt-get install -y "${MISSING_PACKAGES[@]}"
fi

echo "Checking Docker prerequisites..."

DOCKER_PACKAGES=()

if ! command -v docker >/dev/null 2>&1; then
  DOCKER_PACKAGES+=(docker.io docker-compose-v2)
elif ! docker compose version >/dev/null 2>&1; then
  DOCKER_PACKAGES+=(docker-compose-v2)
fi

if (( ${#DOCKER_PACKAGES[@]} > 0 )); then
  echo "Installing missing Docker packages: ${DOCKER_PACKAGES[*]}"

  apt-get update
  apt-get install -y "${DOCKER_PACKAGES[@]}"
fi

echo "Ensuring Docker service is enabled and running..."

systemctl enable --now docker

if id ubuntu >/dev/null 2>&1; then
  if ! id -nG ubuntu | grep -qw docker; then
    echo "Adding ubuntu user to docker group..."
    usermod -aG docker ubuntu
  fi
fi

echo "Docker Engine:"
docker --version

echo "Docker Compose:"
docker compose version

if command -v aws >/dev/null 2>&1; then
  echo "AWS CLI is already installed:"
  aws --version
else
  echo "AWS CLI is not installed. Installing AWS CLI v2..."

  if ! command -v unzip >/dev/null 2>&1; then
    apt-get update
    apt-get install -y unzip
  fi

  ARCH="$(uname -m)"

  case "$ARCH" in
    x86_64)
      AWS_CLI_URL="https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip"
      ;;
    aarch64|arm64)
      AWS_CLI_URL="https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip"
      ;;
    *)
      echo "ERROR: Unsupported architecture: $ARCH"
      exit 1
      ;;
  esac

  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT

  curl -fSL "$AWS_CLI_URL" -o "$TMP_DIR/awscliv2.zip"

  unzip -q "$TMP_DIR/awscliv2.zip" -d "$TMP_DIR"

  "$TMP_DIR/aws/install" \
    --install-dir /usr/local/aws-cli \
    --bin-dir /usr/local/bin

  echo "AWS CLI installed successfully:"
  aws --version
fi