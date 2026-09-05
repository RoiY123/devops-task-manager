#!/usr/bin/env bash

set -Eeuo pipefail

echo "Checking instance prerequisites..."

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is not installed. Installing..."
  apt-get update
  apt-get install -y curl
fi

if command -v aws >/dev/null 2>&1; then
  echo "AWS CLI is already installed:"
  aws --version
  exit 0
fi

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