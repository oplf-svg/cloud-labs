# Reads what the projects have cost, and nothing else. Only cloud-labs, only main, in an environment of its own.

locals {
  cost_principal = "principal://${local.principals}/subject/${local.cost_subject}"

  # For the environment of the same name in cloud-labs.
  cost_secrets = { cost = { GCP_COST_PROJECT_ID = var.bootstrap_project_id } }
}

# Google writes the billing export here, once a person has switched it on in the console. Not in the project that the repos
# deploy into: there, apply may read every dataset and destroy may delete it.
#
# No access blocks here, and no iam_policy or iam_binding on it: Google's own export account becomes an owner that Terraform
# does not know, and without it the export stops and nobody is told.
resource "google_bigquery_dataset" "billing_export" {
  project                    = var.bootstrap_project_id
  dataset_id                 = "billing_export"
  location                   = var.region
  description                = "Written by Google's billing export. Read by the cost identity of cloud-labs."
  delete_contents_on_destroy = false

  lifecycle {
    # A table that is gone is not filled again.
    prevent_destroy = true
  }
}

# Lists the tables and reads their rows. The script adds them up itself, so it needs no right to run a query anywhere.
resource "google_project_iam_custom_role" "cost" {
  project     = var.bootstrap_project_id
  role_id     = "ghaCost"
  title       = "GitHub Actions cost"
  description = "Reads the tables of one dataset. Granted on that dataset only."
  permissions = ["bigquery.tables.get", "bigquery.tables.getData", "bigquery.tables.list"]
}

# On the dataset, so this identity has no role in any project.
resource "google_bigquery_dataset_iam_member" "cost" {
  project    = var.bootstrap_project_id
  dataset_id = google_bigquery_dataset.billing_export.dataset_id
  role       = google_project_iam_custom_role.cost.id
  # How BigQuery calls a principal that is neither a person nor a group nor a service account.
  member = "iamMember:${local.cost_principal}"

  depends_on = [google_iam_workload_identity_pool_provider.github]
}
