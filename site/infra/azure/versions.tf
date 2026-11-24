terraform {
  required_version = ">= 1.17.0, < 2.0.0"

  required_providers {
    # Not azurerm: it would read the key for uploads and keep it in the state.
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.14"
    }
  }

  # The name of the storage account comes from the deploy script.
  backend "azurerm" {
    container_name   = "cloud-labs"
    key              = "site/terraform.tfstate"
    use_azuread_auth = true
    use_oidc         = true
  }
}

provider "azapi" {
  subscription_id            = var.subscription_id
  use_oidc                   = true
  skip_provider_registration = true
}
