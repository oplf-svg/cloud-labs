locals {
  # Which tier a token belongs to, decided by exact match against the literal subjects.
  tier_expression = join(" : ", concat(
    [for tier, subjects in local.tier_subjects : "assertion.sub in ${jsonencode(subjects)} ? \"${tier}\""],
    ["\"none\""],
  ))

  # Tokens with any other subject are refused before IAM looks at them.
  # Apply and destroy must also run on main, on top of the environment's own branch rule.
  trust_condition = join(" || ", [
    "assertion.sub in ${jsonencode(local.tier_subjects.plan)}",
    "(assertion.sub in ${jsonencode(concat(local.tier_subjects.apply, local.tier_subjects.destroy))} && assertion.ref == \"refs/heads/main\")",
  ])
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.bootstrap_project_id
  workload_identity_pool_id = var.pool_id
  display_name              = "GitHub Actions"
  description               = "Short-lived access for GitHub Actions. No service accounts, no keys."

  lifecycle {
    precondition {
      condition = alltrue([
        for key, id in local.identities : can(regex(
          "^repo:oplf-svg@228823995/${id.repo}@[0-9]+:${local.subject_suffix[id.tier]}$",
          id.subject,
        ))
      ])
      error_message = "A subject is not the exact immutable form expected for its tier."
    }
  }
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.bootstrap_project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub"
  description                        = "Accepts 15 exact subjects and nothing else."

  attribute_condition = local.trust_condition

  attribute_mapping = {
    "google.subject" = "assertion.sub"
    "attribute.tier" = local.tier_expression
  }

  # No allowed_audiences: only tokens made for this provider's own name are accepted.
  oidc {
    issuer_uri = local.issuer
  }
}
