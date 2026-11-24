# Asks what the subscription has cost, and nothing else. Only cloud-labs, only main, in an environment of its own.

locals {
  # For the environment of the same name in cloud-labs.
  cost_secrets = { cost = { AZURE_CLIENT_ID = azurerm_user_assigned_identity.cost.client_id } }
}

resource "azurerm_user_assigned_identity" "cost" {
  name                = "id-gha-cloud-labs-cost"
  resource_group_name = azurerm_resource_group.bootstrap.name
  location            = var.region
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "cost" {
  name                      = "github-actions"
  user_assigned_identity_id = azurerm_user_assigned_identity.cost.id
  issuer                    = local.issuer
  audience                  = [local.audience]
  subject                   = local.cost_subject

  lifecycle {
    precondition {
      condition     = can(regex("^repo:oplf-svg@228823995/cloud-labs@[0-9]+:environment:cost:ref:refs/heads/main$", local.cost_subject))
      error_message = "The subject in cost.json is not the exact immutable form expected for the cost identity."
    }
  }
}

# Not the built-in Cost Management Reader: that one may also see every resource group and open support requests.
resource "azurerm_role_definition" "cost" {
  name              = "GitHub Actions cost"
  description       = "Asks what the subscription has cost. Nothing else."
  scope             = local.subscription
  assignable_scopes = [local.subscription]

  permissions {
    actions     = ["Microsoft.CostManagement/query/action", "Microsoft.CostManagement/query/read"]
    not_actions = []
  }
}

resource "azurerm_role_assignment" "cost" {
  scope              = local.subscription
  role_definition_id = azurerm_role_definition.cost.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.cost.principal_id
  principal_type     = "ServicePrincipal"
}
