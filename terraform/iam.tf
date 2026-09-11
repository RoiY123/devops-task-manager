data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    effect = "Allow"

    actions = [
      "sts:AssumeRole"
    ]

    principals {
      type = "Service"

      identifiers = [
        "ec2.amazonaws.com"
      ]
    }
  }
}

resource "aws_iam_role" "app_ssm" {
  name = "task-manager-app-ssm"

  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "app_ssm_core" {
  role       = aws_iam_role.app_ssm.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# AmazonSSMManagedInstanceCore allows reading SSM parameters broadly.
# This explicit deny limits the app instance to its own Parameter Store path.
data "aws_iam_policy_document" "app_parameter_store" {
  statement {
    effect = "Deny"

    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters"
    ]

    not_resources = [
      "arn:aws:ssm:il-central-1:${data.aws_caller_identity.current.account_id}:parameter/task-manager/prod/app/*"
    ]
  }
}

resource "aws_iam_policy" "app_parameter_store" {
  name   = "task-manager-app-parameter-store"
  policy = data.aws_iam_policy_document.app_parameter_store.json
}

resource "aws_iam_role_policy_attachment" "app_parameter_store" {
  role       = aws_iam_role.app_ssm.name
  policy_arn = aws_iam_policy.app_parameter_store.arn
}

resource "aws_iam_instance_profile" "app" {
  name = "task-manager-app-instance-profile"

  role = aws_iam_role.app_ssm.name
}

resource "aws_iam_role" "monitoring_ssm" {
  name = "task-manager-monitoring-ssm"

  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "monitoring_ssm_core" {
  role       = aws_iam_role.monitoring_ssm.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# AmazonSSMManagedInstanceCore allows reading SSM parameters broadly.
# This explicit deny limits the monitoring instance to its own Parameter Store path.
data "aws_iam_policy_document" "monitoring_parameter_store" {
  statement {
    effect = "Deny"

    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters"
    ]

    not_resources = [
      "arn:aws:ssm:il-central-1:${data.aws_caller_identity.current.account_id}:parameter/task-manager/prod/monitoring/*"
    ]
  }
}

resource "aws_iam_policy" "monitoring_parameter_store" {
  name   = "task-manager-monitoring-parameter-store"
  policy = data.aws_iam_policy_document.monitoring_parameter_store.json
}

resource "aws_iam_role_policy_attachment" "monitoring_parameter_store" {
  role       = aws_iam_role.monitoring_ssm.name
  policy_arn = aws_iam_policy.monitoring_parameter_store.arn
}

data "aws_iam_policy_document" "monitoring_cloudwatch" {
  statement {
    effect = "Allow"

    actions = [
      "cloudwatch:GetMetricData",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:ListMetrics",
      "ec2:DescribeRegions",
      "rds:DescribeDBInstances",
      "rds:ListTagsForResource"
    ]

    resources = ["*"]
  }
}

resource "aws_iam_policy" "monitoring_cloudwatch" {
  name   = "task-manager-monitoring-cloudwatch"
  policy = data.aws_iam_policy_document.monitoring_cloudwatch.json
}

resource "aws_iam_role_policy_attachment" "monitoring_cloudwatch" {
  role       = aws_iam_role.monitoring_ssm.name
  policy_arn = aws_iam_policy.monitoring_cloudwatch.arn
}

resource "aws_iam_instance_profile" "monitoring" {
  name = "task-manager-monitoring-instance-profile"

  role = aws_iam_role.monitoring_ssm.name
}
