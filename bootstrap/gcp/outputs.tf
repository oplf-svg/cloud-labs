output "backend_tf" {
  description = "Backend block for this stack's own state. Write it to backend.tf, which git ignores."
  value       = <<-EOT
    terraform {
      backend "gcs" {
        bucket = "${google_storage_bucket.state.name}"
        prefix = "bootstrap"
      }
    }
  EOT
}

output "state_bucket" {
  description = "Bucket for every repo's state. Each repo uses a prefix with its own name."
  value       = google_storage_bucket.state.name
}

# The number shows up in logs, for example in Cloud Run addresses, so GitHub has to know it to hide it.
data "google_project" "deploy" {
  project_id = var.project_id
}

output "github_secrets" {
  description = "Input for scripts/load_secrets.py. The provider is the same for every identity: the token's subject decides the rights."
  sensitive   = true

  value = {
    cloud = "gcp"
    repos = {
      for repo in keys(local.subjects) : repo => merge({
        repository = {
          GCP_PROJECT_ID                 = var.project_id
          GCP_PROJECT_NUMBER             = data.google_project.deploy.number
          GCP_STATE_BUCKET               = google_storage_bucket.state.name
          GCP_WORKLOAD_IDENTITY_PROVIDER = google_iam_workload_identity_pool_provider.github.name
        }
        production      = {}
        nightly-destroy = {}
      }, { for name, secrets in local.cost_secrets : name => secrets if repo == "cloud-labs" })
    }
  }
}

output "trusted_subjects" {
  description = "Every subject the pool trusts."
  value       = sort(concat([for id in local.identities : id.subject], [local.cost_subject]))
}
