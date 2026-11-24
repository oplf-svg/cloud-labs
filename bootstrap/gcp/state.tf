resource "random_id" "suffix" {
  byte_length = 4
}

# Encrypted at rest with Google-managed keys. A customer key would add a fixed monthly cost on each cloud.
resource "google_storage_bucket" "state" {
  project       = var.bootstrap_project_id
  name          = local.bucket
  location      = var.region
  storage_class = "STANDARD"
  force_destroy = var.allow_state_deletion

  public_access_prevention    = "enforced"
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  soft_delete_policy {
    retention_duration_seconds = 2592000 # 30 days
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      days_since_noncurrent_time = 90
      num_newer_versions         = 10
      with_state                 = "ARCHIVED"
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

# The whole access list. It replaces the defaults, which let project Editors and Viewers in.
resource "google_storage_bucket_iam_policy" "state" {
  bucket = google_storage_bucket.state.name

  policy_data = jsonencode({
    bindings = concat(
      [
        {
          role    = "roles/storage.legacyBucketOwner"
          members = ["projectOwner:${var.bootstrap_project_id}"]
        },
        {
          role    = "roles/storage.legacyObjectOwner"
          members = ["projectOwner:${var.bootstrap_project_id}"]
        },
        {
          # Lists object names. Reading an object needs one of the bindings below.
          role    = "roles/storage.legacyBucketReader"
          members = [for tier in sort(keys(local.tier_principals)) : local.tier_principals[tier]]
        },
      ],
      [
        for key, id in local.identities : {
          role    = id.tier == "plan" ? "roles/storage.objectViewer" : "roles/storage.objectUser"
          members = [local.principal[key]]
          condition = {
            title      = "own-state-only"
            expression = "resource.type == \"storage.googleapis.com/Object\" && resource.name.startsWith(\"projects/_/buckets/${local.bucket}/objects/${id.repo}/\")"
          }
        }
      ],
    )
  })

  depends_on = [google_iam_workload_identity_pool_provider.github]
}
