output "backend_tf" {
  description = "Backend block for this stack's own state. Write it to backend.tf, which git ignores."
  value       = <<-EOT
    terraform {
      backend "azurerm" {
        storage_account_name = "${azurerm_storage_account.state.name}"
        container_name       = "bootstrap"
        key                  = "terraform.tfstate"
        use_azuread_auth     = true
        use_cli              = true
      }
    }
  EOT
}

output "state_bucket" {
  description = "Storage account for every repo's state. Each repo uses the container with its own name."
  value       = azurerm_storage_account.state.name
}

output "github_secrets" {
  description = "Input for scripts/load_secrets.py. A job in an environment gets that environment's value, any other job gets the plan identity."
  sensitive   = true

  value = {
    cloud = "azure"
    repos = {
      for repo in keys(local.subjects) : repo => {
        repository = {
          AZURE_CLIENT_ID       = azurerm_user_assigned_identity.ci["${repo}/plan"].client_id
          AZURE_STATE_ACCOUNT   = azurerm_storage_account.state.name
          AZURE_SUBSCRIPTION_ID = var.subscription_id
          AZURE_TENANT_ID       = data.azurerm_client_config.current.tenant_id
        }
        production = {
          AZURE_CLIENT_ID = azurerm_user_assigned_identity.ci["${repo}/apply"].client_id
        }
        nightly-destroy = {
          AZURE_CLIENT_ID = azurerm_user_assigned_identity.ci["${repo}/destroy"].client_id
        }
      }
    }
  }
}

output "trusted_subjects" {
  description = "Every subject this subscription trusts."
  value       = sort([for c in azurerm_federated_identity_credential.ci : c.subject])
}
