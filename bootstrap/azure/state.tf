resource "random_id" "suffix" {
  byte_length = 4
}

# Encrypted at rest with Microsoft-managed keys. A customer key would add a fixed monthly cost on each cloud.
resource "azurerm_storage_account" "state" {
  name                = "tfstate${random_id.suffix.hex}"
  resource_group_name = azurerm_resource_group.bootstrap.name
  location            = var.region
  tags                = local.tags

  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "LRS"

  # No anonymous access, no account keys, no shared links: Entra ID sign-in only.
  allow_nested_items_to_be_public  = false
  shared_access_key_enabled        = false
  local_user_enabled               = false
  default_to_oauth_authentication  = true
  cross_tenant_replication_enabled = false
  allowed_copy_scope               = "AAD"

  https_traffic_only_enabled = true
  min_tls_version            = "TLS1_2"

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 30
    }

    container_delete_retention_policy {
      days = 30
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_container" "state" {
  for_each = local.containers

  name                  = each.key
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

resource "azurerm_storage_management_policy" "state" {
  storage_account_id = azurerm_storage_account.state.id

  rule {
    name    = "old-versions"
    enabled = true

    filters {
      blob_types = ["blockBlob"]
    }

    actions {
      version {
        delete_after_days_since_creation = 90
      }
    }
  }
}

# Each identity reaches its own repo's container. Only apply and destroy can write.
resource "azurerm_role_assignment" "state" {
  for_each = local.identities

  scope                = local.container_scope[each.value.repo]
  role_definition_name = each.value.tier == "plan" ? "Storage Blob Data Reader" : "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.ci[each.key].principal_id
  principal_type       = "ServicePrincipal"

  depends_on = [azurerm_storage_container.state]
}

# Lets you, the person running this, move this stack's own state into the account.
resource "azurerm_role_assignment" "operator" {
  scope                = local.container_scope["bootstrap"]
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id

  depends_on = [azurerm_storage_container.state]
}

# Deleting a storage account deletes what is in it, so nobody can do that by accident.
resource "azurerm_management_lock" "bootstrap" {
  count = var.allow_state_deletion ? 0 : 1

  name       = "keep-github-bootstrap"
  scope      = azurerm_resource_group.bootstrap.id
  lock_level = "CanNotDelete"
  notes      = "Holds the GitHub Actions identities and the Terraform state."

  depends_on = [
    azurerm_federated_identity_credential.ci,
    azurerm_role_assignment.operator,
    azurerm_role_assignment.state,
    azurerm_storage_management_policy.state,
  ]
}
