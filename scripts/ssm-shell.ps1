param (
    [Parameter(Mandatory = $true)]
    [ValidateSet("app", "monitoring")]
    [string]$Target
)

$ErrorActionPreference = "Stop"

$AwsProfile = "task-manager-terraform"
$AwsRegion = "il-central-1"

$InstanceName = switch ($Target) {
    "app" { "task-manager-prod-api" }
    "monitoring" { "task-manager-prod-monitoring" }
}

Write-Host "Resolving running EC2 instance: $InstanceName"

$InstanceId = aws ec2 describe-instances `
    --filters `
        "Name=tag:Name,Values=$InstanceName" `
        "Name=instance-state-name,Values=running" `
    --query "Reservations[0].Instances[0].InstanceId" `
    --output text `
    --profile $AwsProfile `
    --region $AwsRegion

if (-not $InstanceId -or $InstanceId -eq "None") {
    Write-Error "No running EC2 instance found for $InstanceName."
    exit 1
}

Write-Host "Starting SSM session with $InstanceId"

aws ssm start-session `
    --target $InstanceId `
    --profile $AwsProfile `
    --region $AwsRegion