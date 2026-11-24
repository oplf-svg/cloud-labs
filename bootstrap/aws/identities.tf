resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://${local.issuer}"
  client_id_list = [local.audience]
}

# One role per repo and tier. Each trusts a single, literal subject.
resource "aws_iam_role" "ci" {
  for_each = local.identities

  name                 = "gha-${each.value.repo}-${each.value.tier}"
  path                 = local.ci_path
  description          = "GitHub Actions ${each.value.tier} for ${each.value.repo}"
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = merge(
          {
            "${local.issuer}:aud" = local.audience
            "${local.issuer}:sub" = each.value.subject
          },
          # A second check on top of the environment's own branch rule.
          each.value.tier == "plan" ? {} : { "${local.issuer}:ref" = "refs/heads/main" },
        )
      }
    }]
  })

  lifecycle {
    precondition {
      condition = can(regex(
        "^repo:oplf-svg@228823995/${each.value.repo}@[0-9]+:${local.subject_suffix[each.value.tier]}$",
        each.value.subject,
      ))
      error_message = "Subject for ${each.key} is not the exact immutable form expected for its tier."
    }
  }

  depends_on = [aws_iam_openid_connect_provider.github]
}

resource "aws_iam_role_policy_attachment" "ci" {
  for_each = local.attachments

  role       = aws_iam_role.ci[each.value.identity].name
  policy_arn = each.value.policy_arn
}

resource "aws_iam_role_policy" "state" {
  for_each = local.identities

  name   = "terraform-state"
  role   = aws_iam_role.ci[each.key].name
  policy = jsonencode(local.state_policies[each.key])
}
