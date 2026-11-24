locals {
  issuer   = "https://token.actions.githubusercontent.com"
  audience = "api://AzureADTokenExchange"

  # The exact OIDC subjects, one per repo and tier. All three clouds read this file.
  subjects = jsondecode(file("${path.module}/../subjects.json"))

  # What each tier's subject must end with. Anything else stops the plan. GitHub puts the branch at the end because the
  # repos' subject template says so, and a token without it is refused.
  subject_suffix = {
    plan    = "environment:plan:ref:refs/heads/main"
    apply   = "environment:production:ref:refs/heads/main"
    destroy = "environment:nightly-destroy:ref:refs/heads/main"
  }

  # The one identity that reads costs and nothing else. It is not a tier: every tier but plan may write state, and all of
  # them may list its names.
  cost_subject = jsondecode(file("${path.module}/../cost.json"))["cloud-labs"]["cost"]

  identities = merge([
    for repo, tiers in local.subjects : {
      for tier, subject in tiers : "${repo}/${tier}" => {
        repo    = repo
        tier    = tier
        subject = subject
      }
    }
  ]...)

  subscription = "/subscriptions/${var.subscription_id}"

  tags = {
    managed-by = "terraform"
    stack      = "github-bootstrap"
  }

  # One state container per repo, plus one for this stack's own state.
  containers = toset(concat(keys(local.subjects), ["bootstrap"]))

  container_scope = {
    for name in local.containers : name => "${azurerm_storage_account.state.id}/blobServices/default/containers/${name}"
  }
}

data "azurerm_client_config" "current" {}
