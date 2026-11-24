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

output "workload_identity_provider" {
  description = "Provider name for every repo and tier, to store later as a GitHub Actions secret. It contains the bootstrap project's number."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "trusted_subjects" {
  description = "Every subject the pool trusts."
  value       = sort([for id in local.identities : id.subject])
}
