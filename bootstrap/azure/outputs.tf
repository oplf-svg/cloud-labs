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

output "client_ids" {
  description = "Client id per repo and tier, to store later as GitHub Actions secrets."
  value       = { for key, identity in azurerm_user_assigned_identity.ci : key => identity.client_id }
}

output "tenant_id" {
  description = "Directory the identities live in."
  value       = data.azurerm_client_config.current.tenant_id
}

output "resource_groups" {
  description = "Resource group each repo deploys into."
  value       = { for repo, group in azurerm_resource_group.repo : repo => group.name }
}

output "trusted_subjects" {
  description = "Every subject this subscription trusts."
  value       = sort([for c in azurerm_federated_identity_credential.ci : c.subject])
}
