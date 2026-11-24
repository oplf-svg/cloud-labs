# Runs against mocked providers: no credentials, nothing is created.

mock_provider "google" {
  mock_resource "google_iam_workload_identity_pool" {
    defaults = { name = "projects/123456789012/locations/global/workloadIdentityPools/github-actions" }
  }

  # A sample of what Google offers, with dangerous names that must never be picked up.
  mock_data "google_iam_testable_permissions" {
    defaults = {
      permissions = [
        { name = "run.services.get", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "run.services.list", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "run.services.getIamPolicy", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "run.services.setIamPolicy", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "run.services.create", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "run.services.delete", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "storage.buckets.get", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "storage.buckets.delete", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "storage.objects.get", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "storage.objects.delete", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "storage.objects.list", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "secretmanager.versions.access", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "secretmanager.versions.destroy", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "logging.logEntries.list", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "datastore.entities.get", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "container.secrets.get", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "bigquery.tables.getData", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "iam.serviceAccounts.create", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "iam.serviceAccounts.delete", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "iam.serviceAccounts.actAs", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "iam.serviceAccounts.setIamPolicy", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "iam.serviceAccountKeys.create", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "iam.roles.delete", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "iam.roles.update", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "iam.googleapis.com/workloadIdentityPools.delete", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "iam.googleapis.com/workloadIdentityPoolProviders.update", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "resourcemanager.projects.get", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "resourcemanager.projects.getIamPolicy", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "resourcemanager.projects.setIamPolicy", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
        { name = "resourcemanager.projects.delete", title = "", stage = "GA", api_disabled = false, custom_support_level = "SUPPORTED" },
      ]
    }
  }
}

mock_provider "random" {
  mock_resource "random_id" {
    defaults = { hex = "0a1b2c3d" }
  }
}

variables {
  project_id           = "example-project-1"
  bootstrap_project_id = "example-bootstrap-1"

  # Written out again here on purpose, so that a change to subjects.json fails the test.
  repo_ids = {
    webhook-platform   = 1469384538
    k8s-platform-lab   = 1469385215
    ai-ops-agent       = 1469385344
    event-pipeline-lab = 1469385472
    cloud-labs         = 1469385611
  }
  suffixes = {
    plan    = "pull_request"
    apply   = "environment:production"
    destroy = "environment:nightly-destroy"
  }
}

run "trust" {
  command = apply

  assert {
    condition = toset(flatten(regexall("\"(repo:[^\"]+)\"", google_iam_workload_identity_pool_provider.github.attribute_condition))) == toset(flatten([
      for repo, id in var.repo_ids : [for suffix in values(var.suffixes) : "repo:oplf-svg@228823995/${repo}@${id}:${suffix}"]
    ]))
    error_message = "The provider must accept exactly the 15 literal subjects."
  }

  assert {
    condition = google_iam_workload_identity_pool_provider.github.attribute_mapping == tomap({
      "google.subject" = "assertion.sub"
      "attribute.tier" = join(" : ", concat(
        [for tier in ["apply", "destroy", "plan"] : "assertion.sub in ${jsonencode(sort([for repo, id in var.repo_ids : "repo:oplf-svg@228823995/${repo}@${id}:${var.suffixes[tier]}"]))} ? \"${tier}\""],
        ["\"none\""],
      ))
    })
    error_message = "A token's tier must come from an exact match on its subject."
  }

  assert {
    condition = google_iam_workload_identity_pool_provider.github.attribute_condition == join(" || ", [
      "assertion.sub in ${jsonencode(sort([for repo, id in var.repo_ids : "repo:oplf-svg@228823995/${repo}@${id}:pull_request"]))}",
      "(assertion.sub in ${jsonencode(concat(
        sort([for repo, id in var.repo_ids : "repo:oplf-svg@228823995/${repo}@${id}:environment:production"]),
        sort([for repo, id in var.repo_ids : "repo:oplf-svg@228823995/${repo}@${id}:environment:nightly-destroy"]),
      ))} && assertion.ref == \"refs/heads/main\")",
    ])
    error_message = "Apply and destroy must also require the main branch."
  }

  assert {
    condition = (
      !can(regex("\\*|startsWith|endsWith|contains|matches", google_iam_workload_identity_pool_provider.github.attribute_condition))
      && length(google_iam_workload_identity_pool_provider.github.attribute_condition) <= 4096
      && alltrue([for e in values(google_iam_workload_identity_pool_provider.github.attribute_mapping) : length(e) <= 2048])
      && alltrue([for s in output.trusted_subjects : length(s) <= 127])
    )
    error_message = "No pattern matching, and within Google's length limits."
  }

  assert {
    condition = (
      google_iam_workload_identity_pool_provider.github.oidc[0].issuer_uri == "https://token.actions.githubusercontent.com"
      && google_iam_workload_identity_pool_provider.github.oidc[0].allowed_audiences == null
    )
    error_message = "Only GitHub's issuer, and only tokens made for this provider."
  }
}

run "permissions" {
  command = apply

  assert {
    condition     = google_project_iam_custom_role.read.permissions == toset(["resourcemanager.projects.get", "resourcemanager.projects.getIamPolicy", "run.services.get", "run.services.getIamPolicy", "run.services.list", "storage.buckets.get"])
    error_message = "The read role may only read configuration."
  }

  assert {
    condition     = google_project_iam_custom_role.delete.permissions == toset(["iam.serviceAccounts.delete", "run.services.delete", "secretmanager.versions.destroy", "storage.buckets.delete", "storage.objects.delete", "storage.objects.list"])
    error_message = "The delete role may only delete, and never the trust, roles or the project."
  }

  assert {
    condition     = google_project_iam_custom_role.service_accounts.permissions == toset(["iam.serviceAccounts.create", "iam.serviceAccounts.delete"])
    error_message = "Apply may manage service accounts, but not their keys or who may use them."
  }

  assert {
    condition     = google_project_iam_custom_role.project_grants.permissions == toset(["resourcemanager.projects.get", "resourcemanager.projects.getIamPolicy", "resourcemanager.projects.setIamPolicy"])
    error_message = "The conditional role may only read and change project access."
  }

  # Google refuses a longer list.
  assert {
    condition     = length(local.grantable_roles) <= 10 && length(local.grantable_roles) == length(toset(local.grantable_roles))
    error_message = "At most ten roles can be grantable."
  }

  # setIamPolicy appears in one role only, and that role is granted only under the condition.
  assert {
    condition = (
      length([for r in [google_project_iam_custom_role.read, google_project_iam_custom_role.delete, google_project_iam_custom_role.service_accounts] : r if length([for p in r.permissions : p if can(regex("(?i)setIamPolicy|actAs", p))]) > 0]) == 0
      && length(google_project_iam_member.apply_grants.condition) == 1
    )
    error_message = "Changing access must always be limited by the condition."
  }

  # The delete role may also hold the three helper permissions named here, and nothing else.
  assert {
    condition = alltrue([
      for p in local.delete_permissions :
      can(regex("\\.(delete[A-Za-z]*|destroy|detachSubscription|removePeering|undeploy)$", p)) || contains(["compute.networks.updatePolicy", "dns.changes.create", "storage.objects.list"], p)
    ])
    error_message = "Every delete permission must remove something."
  }

  assert {
    condition     = alltrue([for p in local.read_permissions : can(regex("\\.(get|getIamPolicy|getMetadata|list|use)$", p))])
    error_message = "Every read permission must be a read."
  }

  assert {
    condition = alltrue([
      for m in concat(values(google_project_iam_member.apply), [google_project_iam_member.apply_service_accounts, google_project_iam_member.apply_grants]) :
      m.member == "principalSet://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/github-actions/attribute.tier/apply"
    ])
    error_message = "Deploy rights belong to the apply tier only."
  }

  assert {
    condition = length(setintersection(
      toset(concat(local.apply_roles, local.grantable_roles)),
      toset(["roles/owner", "roles/editor", "roles/viewer", "roles/admin", "roles/writer", "roles/compute.admin", "roles/bigquery.admin", "roles/aiplatform.admin", "roles/iam.admin", "roles/iam.securityAdmin", "roles/iam.serviceAccountAdmin", "roles/iam.serviceAccountKeyAdmin", "roles/iam.serviceAccountTokenCreator", "roles/iam.workloadIdentityPoolAdmin", "roles/resourcemanager.projectIamAdmin"]),
    )) == 0
    error_message = "Roles that administer access must be neither held nor grantable."
  }

  assert {
    condition     = startswith(google_project_iam_member.apply_grants.condition[0].expression, "api.getAttribute(\"iam.googleapis.com/modifiedGrantsByRole\", []).hasOnly([")
    error_message = "Apply may change project access only under a condition."
  }

  assert {
    condition = alltrue([
      for m in concat(values(google_project_iam_member.apply), values(google_project_iam_member.read), [google_project_iam_member.delete, google_project_iam_member.apply_service_accounts, google_project_iam_member.apply_grants]) :
      m.project == "example-project-1"
    ])
    error_message = "No pipeline may have a project role in the bootstrap project."
  }
}

run "state" {
  command = apply

  assert {
    condition = (
      google_storage_bucket.state.project == "example-bootstrap-1"
      && google_iam_workload_identity_pool.github.project == "example-bootstrap-1"
      && google_iam_workload_identity_pool_provider.github.project == "example-bootstrap-1"
    )
    error_message = "The trust and the state belong in the bootstrap project."
  }

  assert {
    condition = (
      google_storage_bucket.state.public_access_prevention == "enforced"
      && google_storage_bucket.state.uniform_bucket_level_access
      && google_storage_bucket.state.versioning[0].enabled
      && google_storage_bucket.state.soft_delete_policy[0].retention_duration_seconds == 2592000
    )
    error_message = "The state bucket must block public access, use uniform access and keep versions."
  }

  assert {
    condition = { for b in jsondecode(google_storage_bucket_iam_policy.state.policy_data).bindings : b.members[0] => "${b.role} ${b.condition.expression}" if can(b.condition) } == merge([
      for repo, id in var.repo_ids : {
        for tier, suffix in var.suffixes :
        "principal://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/github-actions/subject/repo:oplf-svg@228823995/${repo}@${id}:${suffix}" =>
        "${tier == "plan" ? "roles/storage.objectViewer" : "roles/storage.objectUser"} resource.type == \"storage.googleapis.com/Object\" && resource.name.startsWith(\"projects/_/buckets/tfstate-0a1b2c3d/objects/${repo}/\")"
      }
    ]...)
    error_message = "A subject may only reach its own repo's state, and plan may only read it."
  }

  assert {
    condition = alltrue([
      for b in jsondecode(google_storage_bucket_iam_policy.state.policy_data).bindings :
      length(setintersection(toset(b.members), toset(["allUsers", "allAuthenticatedUsers", "projectEditor:example-bootstrap-1", "projectViewer:example-bootstrap-1", "projectOwner:example-project-1"]))) == 0
    ])
    error_message = "No public access, and none for project Editors or Viewers."
  }

  assert {
    condition     = length(jsondecode(google_storage_bucket_iam_policy.state.policy_data).bindings) == 18
    error_message = "Three shared bindings and one per subject."
  }
}

run "rejects_a_wrong_project_id" {
  command         = plan
  expect_failures = [var.project_id]

  variables {
    project_id = "My Project"
  }
}

run "rejects_one_project_for_both" {
  command         = plan
  expect_failures = [var.bootstrap_project_id]

  variables {
    bootstrap_project_id = "example-project-1"
  }
}

run "rejects_risky_extras" {
  command         = plan
  expect_failures = [var.plan_extra, var.apply_extra, var.destroy_extra]

  variables {
    plan_extra    = ["secretmanager.versions.access"]
    apply_extra   = ["roles/editor"]
    destroy_extra = ["run.services.setIamPolicy"]
  }
}
