# Reads what the account has cost, and nothing else. Only cloud-labs, only main, in an environment of its own.

locals {
  # The only call that this role may make.
  cost_actions = ["ce:GetCostAndUsage"]

  # For the environment of the same name in cloud-labs.
  cost_secrets = { cost = { AWS_ROLE_ARN = aws_iam_role.cost.arn } }
}

resource "aws_iam_role" "cost" {
  name = "gha-cloud-labs-cost"
  # Under the same path as the other roles, so that everything that protects those protects this one.
  path                 = local.ci_path
  description          = "GitHub Actions cost for cloud-labs"
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.issuer}:aud" = local.audience
          "${local.issuer}:sub" = local.cost_subject
          "${local.issuer}:ref" = "refs/heads/main"
        }
      }
    }]
  })

  lifecycle {
    precondition {
      condition     = can(regex("^repo:oplf-svg@228823995/cloud-labs@[0-9]+:environment:cost:ref:refs/heads/main$", local.cost_subject))
      error_message = "The subject in cost.json is not the exact immutable form expected for the cost identity."
    }
  }

  depends_on = [aws_iam_openid_connect_provider.github]
}

# No managed policy, and not the guardrails: they deny everything about costs.
resource "aws_iam_role_policy" "cost" {
  name = "read-costs"
  role = aws_iam_role.cost.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadCosts"
        Effect   = "Allow"
        Action   = local.cost_actions
        Resource = "*"
      },
      {
        # Holds even if someone attaches more to this role.
        Sid       = "NothingElse"
        Effect    = "Deny"
        NotAction = local.cost_actions
        Resource  = "*"
      },
    ]
  })
}
