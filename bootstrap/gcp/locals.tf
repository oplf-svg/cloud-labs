locals {
  issuer = "https://token.actions.githubusercontent.com"

  # The exact OIDC subjects, one per repo and tier. All three clouds read this file.
  subjects = jsondecode(file("${path.module}/../subjects.json"))

  # What each tier's subject must end with. Anything else stops the plan.
  subject_suffix = {
    plan    = "pull_request"
    apply   = "environment:production"
    destroy = "environment:nightly-destroy"
  }

  identities = merge([
    for repo, tiers in local.subjects : {
      for tier, subject in tiers : "${repo}/${tier}" => {
        repo    = repo
        tier    = tier
        subject = subject
      }
    }
  ]...)

  tier_subjects = {
    for tier in keys(local.subject_suffix) : tier => sort([for id in local.identities : id.subject if id.tier == tier])
  }

  principals = "iam.googleapis.com/${google_iam_workload_identity_pool.github.name}"

  # One exact subject.
  principal = { for key, id in local.identities : key => "principal://${local.principals}/subject/${id.subject}" }

  # The five exact subjects of a tier, see tier_expression in identities.tf.
  tier_principals = { for tier in keys(local.subject_suffix) : tier => "principalSet://${local.principals}/attribute.tier/${tier}" }

  bucket = "tfstate-${random_id.suffix.hex}"
}
