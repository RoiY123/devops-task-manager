#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$SCRIPT_DIR/../terraform"

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <terraform command> [arguments...]"
  echo "Example: $0 plan"
  echo "Example: $0 apply"
  exit 1
fi

echo "Detecting current public IPv4 address..."

PUBLIC_IP="$(curl --fail --silent --show-error https://checkip.amazonaws.com)"
PUBLIC_IP="${PUBLIC_IP//$'\r'/}"
PUBLIC_IP="${PUBLIC_IP//$'\n'/}"

if [[ ! "$PUBLIC_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "ERROR: Failed to detect a valid public IPv4 address."
  exit 1
fi

export TF_VAR_admin_allowed_cidr="${PUBLIC_IP}/32"

echo "Using admin CIDR: $TF_VAR_admin_allowed_cidr"

cd "$TERRAFORM_DIR"

terraform "$@"