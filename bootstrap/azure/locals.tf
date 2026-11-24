locals {
  issuer   = "https://token.actions.githubusercontent.com"
  audience = "api://AzureADTokenExchange"

  # The exact OIDC subjects, one per repo and tier. All three clouds read this file.
  subjects = jsondecode(file("${path.module}/../subjects.json"))

  # What each tier's subject must end with. Anything else stops the plan.
  subject_suffix = {
    plan    = "environment:plan"
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
