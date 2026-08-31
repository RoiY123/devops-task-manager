# Registers github actions as a trusted OIDC identity provider in AWS
resource "aws_iam_openid_connect_provider" "github_actions" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com"
  ]
}

# Trust policy: defines who is allowed to assume the github deployment role
# restricted to this repo and the main branch
data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    effect = "Allow"

    actions = [
      "sts:AssumeRoleWithWebIdentity"
    ]

    principals {
      type = "Federated"

      identifiers = [
        aws_iam_openid_connect_provider.github_actions.arn
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"

      values = [
        "sts.amazonaws.com"
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"

      values = [
        "repo:RoiY123/devops-task-manager:ref:refs/heads/main"
      ]
    }
  }
}

# IAM role that github actions temporarily assumes through OIDC
resource "aws_iam_role" "github_actions_deploy" {
  name = "task-manager-github-deploy"

  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json
}

# Permission policy: defines what the github deployment role is allowed to do
# allows SSM commands only against the application EC2 and allows reading command results
data "aws_iam_policy_document" "github_actions_deploy" {
  statement {
    effect = "Allow"

    actions = [
      "ssm:SendCommand"
    ]

    resources = [
      aws_instance.app.arn,
      "arn:aws:ssm:il-central-1::document/AWS-RunShellScript"
    ]
  }

  statement {
    effect = "Allow"

    actions = [
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations"
    ]

    resources = [
      "*"
    ]
  }
}

# Creates the permission policy as a real AWS managed IAM policy
resource "aws_iam_policy" "github_actions_deploy" {
  name = "task-manager-github-deploy"

  policy = data.aws_iam_policy_document.github_actions_deploy.json
}

# Attaches the deployment permission policy to the github actions IAM role
resource "aws_iam_role_policy_attachment" "github_actions_deploy" {
  role       = aws_iam_role.github_actions_deploy.name
  policy_arn = aws_iam_policy.github_actions_deploy.arn
}
