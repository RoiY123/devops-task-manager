#!/usr/bin/env bash
# Opens an interactive SSM session on a production instance.
# Usage: ./scripts/ssm-shell.sh app|monitoring

set -euo pipefail

aws_profile="task-manager-terraform"
aws_region="il-central-1"

case "${1:-}" in
  app) instance_name="task-manager-prod-api" ;;
  monitoring) instance_name="task-manager-prod-monitoring" ;;
  *)
    echo "Usage: $0 app|monitoring" >&2
    exit 2
    ;;
esac

echo "Resolving running EC2 instance: $instance_name"

instance_id=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$instance_name" "Name=instance-state-name,Values=running" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text \
  --profile "$aws_profile" \
  --region "$aws_region")

# The Windows AWS CLI can end its output with a carriage return.
instance_id=${instance_id//$'\r'/}

if [[ -z "$instance_id" || "$instance_id" == "None" ]]; then
  echo "No running EC2 instance found for $instance_name." >&2
  exit 1
fi

echo "Starting SSM session with $instance_id"

exec aws ssm start-session \
  --target "$instance_id" \
  --profile "$aws_profile" \
  --region "$aws_region"
