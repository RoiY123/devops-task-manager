#!/usr/bin/env bash
# Forwards a monitoring interface from the monitoring instance to this computer.
# Usage: ./scripts/ssm-tunnel.sh grafana|prometheus|alertmanager [local-port]

set -euo pipefail

aws_profile="task-manager-terraform"
aws_region="il-central-1"
instance_name="task-manager-prod-monitoring"

case "${1:-}" in
  grafana) remote_port=3000 ;;
  prometheus) remote_port=9090 ;;
  alertmanager) remote_port=9093 ;;
  *)
    echo "Usage: $0 grafana|prometheus|alertmanager [local-port]" >&2
    exit 2
    ;;
esac

local_port="${2:-$remote_port}"

if [[ ! "$local_port" =~ ^[0-9]+$ ]]; then
  echo "Local port must be a number, got '$local_port'." >&2
  exit 2
fi

echo "Resolving running monitoring EC2 instance..."

instance_id=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$instance_name" "Name=instance-state-name,Values=running" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text \
  --profile "$aws_profile" \
  --region "$aws_region")

# The Windows AWS CLI can end its output with a carriage return.
instance_id=${instance_id//$'\r'/}

if [[ -z "$instance_id" || "$instance_id" == "None" ]]; then
  echo "No running monitoring EC2 instance found." >&2
  exit 1
fi

echo "Starting $1 tunnel: http://localhost:$local_port"
echo "Keep this terminal open while using it; press Ctrl+C to close."

exec aws ssm start-session \
  --target "$instance_id" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "portNumber=$remote_port,localPortNumber=$local_port" \
  --profile "$aws_profile" \
  --region "$aws_region"
