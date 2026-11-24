terraform {
  required_version = ">= 1.17.0, < 2.0.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.14"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
  }
}

provider "azurerm" {
  subscription_id     = var.subscription_id
  storage_use_azuread = true

  # Register only what this stack needs.
  resource_provider_registrations = "none"
  resource_providers_to_register  = ["Microsoft.ManagedIdentity", "Microsoft.Storage"]

  features {}
}
