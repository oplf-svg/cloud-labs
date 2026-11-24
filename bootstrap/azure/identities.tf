# Holds the identities and the state account. No pipeline has any rights here.
resource "azurerm_resource_group" "bootstrap" {
  name     = "rg-github-bootstrap"
  location = var.region
  tags     = local.tags
}

# One empty resource group per repo. Each pipeline can act only inside its own.
resource "azurerm_resource_group" "repo" {
  for_each = local.subjects

  name     = "rg-${each.key}"
  location = var.region
  tags     = local.tags
}

# Managed identities cannot have passwords or certificates.
resource "azurerm_user_assigned_identity" "ci" {
  for_each = local.identities

  name                = "id-gha-${each.value.repo}-${each.value.tier}"
  resource_group_name = azurerm_resource_group.bootstrap.name
  location            = var.region
  tags                = local.tags
}

# Each identity trusts a single, literal subject.
resource "azurerm_federated_identity_credential" "ci" {
  for_each = local.identities

  name                      = "github-actions"
  user_assigned_identity_id = azurerm_user_assigned_identity.ci[each.key].id
  issuer                    = local.issuer
  audience                  = [local.audience]
  subject                   = each.value.subject

  lifecycle {
    precondition {
      condition = can(regex(
        "^repo:oplf-svg@228823995/${each.value.repo}@[0-9]+:${local.subject_suffix[each.value.tier]}$",
        each.value.subject,
      ))
      error_message = "Subject for ${each.key} is not the exact immutable form expected for its tier."
    }
  }
}
