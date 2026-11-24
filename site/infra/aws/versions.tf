terraform {
  required_version = ">= 1.17.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
    }
  }

  # The name of the bucket comes from the deploy script.
  backend "s3" {
    key          = "cloud-labs/site/terraform.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region              = "eu-west-2"
  allowed_account_ids = [var.account_id]

  default_tags {
    tags = {
      managed-by = "terraform"
      stack      = "site"
    }
  }
}
