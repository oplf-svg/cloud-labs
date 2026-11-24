terraform {
  required_version = ">= 1.17.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.12"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # Cloud Shell signs in as you. Without this, calls are counted against a project Google owns.
  user_project_override = true
  billing_project       = var.bootstrap_project_id

  default_labels = {
    managed-by = "terraform"
    stack      = "github-bootstrap"
  }
}
