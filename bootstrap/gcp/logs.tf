locals {
  # What a container on Cloud Run prints. No requests, no database, nothing that Google says about us.
  shown_logs = { stderr = "run.googleapis.com/stderr", stdout = "run.googleapis.com/stdout" }
}

# So that a failed start says why. Two views, because the description of Google's API allows no "or" in a filter. The audit
# log, with the addresses of whoever signed in, is in another bucket. Apply may change a view (logging.configWriter), so this
# keeps a script from seeing too much by mistake. It is no wall against apply.
resource "google_logging_log_view" "containers" {
  for_each = local.shown_logs

  name        = "containers-${each.key}"
  parent      = "projects/${var.project_id}"
  location    = "global"
  bucket      = "_Default" # the short name: with the long one, the provider stops in the middle of an apply
  description = "What the containers on Cloud Run print to ${each.key}. Nothing else."
  filter      = "SOURCE(\"projects/${var.project_id}\") AND LOG_ID(\"${each.value}\")"
}

resource "google_logging_log_view_iam_member" "apply" {
  for_each = google_logging_log_view.containers

  parent   = each.value.parent
  location = each.value.location
  bucket   = each.value.bucket
  name     = each.value.name
  role     = "roles/logging.viewAccessor"
  member   = local.tier_principals["apply"]

  depends_on = [google_iam_workload_identity_pool_provider.github]
}
