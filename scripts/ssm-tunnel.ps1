param (
    [Parameter(Mandatory = $true)]
    [ValidateSet("grafana", "prometheus", "alertmanager")]
    [string]$Service,

    [int]$LocalPort = 0
)

$ErrorActionPreference = "Stop"

$AwsProfile = "task-manager-terraform"
$AwsRegion = "il-central-1"
$InstanceName = "task-manager-prod-monitoring"

$RemotePort = switch ($Service) {
    "grafana" { 3000 }
    "prometheus" { 9090 }
    "alertmanager" { 9093 }
}

if ($LocalPort -eq 0) {
    $LocalPort = $RemotePort
}

Write-Host "Resolving running monitoring EC2 instance..."

$InstanceId = aws ec2 describe-instances `
    --filters `
        "Name=tag:Name,Values=$InstanceName" `
        "Name=instance-state-name,Values=running" `
    --query "Reservations[0].Instances[0].InstanceId" `
    --output text `
    --profile $AwsProfile `
    --region $AwsRegion

if (-not $InstanceId -or $InstanceId -eq "None") {
    Write-Error "No running monitoring EC2 instance found."
    exit 1
}

Write-Host "Starting $Service tunnel"
Write-Host "Local port:  $LocalPort"
Write-Host "Remote port: $RemotePort"
Write-Host "Keep this terminal open while using the tunnel."

aws ssm start-session `
    --target $InstanceId `
    --document-name AWS-StartPortForwardingSession `
    --parameters "portNumber=$RemotePort,localPortNumber=$LocalPort" `
    --profile $AwsProfile `
    --region $AwsRegion