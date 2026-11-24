# Runs against mocked providers: no credentials, nothing is created.

mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "210987654321" }
  }

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
    plan    = "environment:plan:ref:refs/heads/main"
    apply   = "environment:production:ref:refs/heads/main"
    destroy = "environment:nightly-destroy:ref:refs/heads/main"
  }
  cost_subject = "repo:oplf-svg@228823995/cloud-labs@1469385611:environment:cost:ref:refs/heads/main"
}

run "trust" {
  command = apply

  assert {
    condition = toset(flatten(regexall("\"(repo:[^\"]+)\"", google_iam_workload_identity_pool_provider.github.attribute_condition))) == toset(concat([var.cost_subject], flatten([
      for repo, id in var.repo_ids : [for suffix in values(var.suffixes) : "repo:oplf-svg@228823995/${repo}@${id}:${suffix}"]
    ])))
    error_message = "The provider must accept exactly the 16 literal subjects."
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

  # The cost identity has no tier, and nothing is ever given to those that have none.
  assert {
    condition = (
      !strcontains(google_iam_workload_identity_pool_provider.github.attribute_mapping["attribute.tier"], "environment:cost")
      && toset(keys(local.tier_principals)) == toset(["plan", "apply", "destroy"])
      && alltrue([
        for m in concat(
          [for m in concat(values(google_project_iam_member.apply), values(google_project_iam_member.read), [google_project_iam_member.delete, google_project_iam_member.apply_service_accounts, google_project_iam_member.apply_grants, google_project_iam_member.apply_more_grants, google_project_iam_member.census]) : m.member],
          [google_bigquery_dataset_iam_member.cost.member], [for m in values(google_logging_log_view_iam_member.apply) : m.member],
          flatten([for b in jsondecode(google_storage_bucket_iam_policy.state.policy_data).bindings : b.members]),
        ) : !strcontains(m, "/*") && !strcontains(m, "attribute.tier/none") && (!strcontains(m, "/attribute.") || can(regex("/attribute[.]tier/(plan|apply|destroy)$", m)))
      ])
    )
    error_message = "Nothing may be given to a token without a tier, and the cost identity must be none."
  }

  assert {
    condition = google_iam_workload_identity_pool_provider.github.attribute_condition == join(" && ", [
      "assertion.sub in ${jsonencode(sort(concat([var.cost_subject], flatten([
        for repo, id in var.repo_ids : [for suffix in values(var.suffixes) : "repo:oplf-svg@228823995/${repo}@${id}:${suffix}"]
      ]))))}",
      "assertion.ref == \"refs/heads/main\"",
    ])
    error_message = "Every subject must also require the main branch."
  }

  assert {
    condition = alltrue([
      for s in flatten(regexall("\"(repo:[^\"]+)\"", google_iam_workload_identity_pool_provider.github.attribute_condition)) : can(regex(":environment:(plan|production|nightly-destroy|cost):ref:refs/heads/main$", s))
    ])
    error_message = "Only jobs in one of the four environments and on main may be trusted, so never a pull request."
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

  # Only the night run of cloud-labs, and no list of offered names decides about it.
  assert {
    condition = (
      google_project_iam_custom_role.census.permissions == toset(["cloudasset.assets.searchAllResources"])
      && google_project_iam_custom_role.census.project == "example-project-1"
      && google_project_iam_member.census.role == google_project_iam_custom_role.census.id
      && google_project_iam_member.census.member == "principal://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/github-actions/subject/repo:oplf-svg@228823995/cloud-labs@1469385611:environment:nightly-destroy:ref:refs/heads/main"
    )
    error_message = "Only the destroy identity of cloud-labs may search the project, and it may do nothing else by that."
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
    error_message = "At most ten roles can be grantable in one list."
  }

  assert {
    condition     = local.more_grantable_roles == ["roles/cloudsql.instanceUser"] && length(setintersection(toset(local.more_grantable_roles), toset(local.grantable_roles))) == 0
    error_message = "The second list holds one role, which is not in the first."
  }

  # setIamPolicy appears in one role only, and that role is granted only under the condition.
  assert {
    condition = (
      length([for r in [google_project_iam_custom_role.read, google_project_iam_custom_role.delete, google_project_iam_custom_role.service_accounts] : r if length([for p in r.permissions : p if can(regex("(?i)setIamPolicy|actAs", p))]) > 0]) == 0
      && length(google_project_iam_member.apply_grants.condition) == 1
      && length(google_project_iam_member.apply_more_grants.condition) == 1
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
      for m in concat(values(google_project_iam_member.apply), [google_project_iam_member.apply_service_accounts, google_project_iam_member.apply_grants, google_project_iam_member.apply_more_grants]) :
      m.member == "principalSet://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/github-actions/attribute.tier/apply"
    ])
    error_message = "Deploy rights belong to the apply tier only."
  }

  assert {
    condition = length(setintersection(
      toset(concat(local.apply_roles, local.grantable_roles, local.more_grantable_roles)),
      toset(["roles/owner", "roles/editor", "roles/viewer", "roles/admin", "roles/writer", "roles/compute.admin", "roles/bigquery.admin", "roles/aiplatform.admin", "roles/iam.admin", "roles/iam.securityAdmin", "roles/iam.serviceAccountAdmin", "roles/iam.serviceAccountKeyAdmin", "roles/iam.serviceAccountTokenCreator", "roles/iam.workloadIdentityPoolAdmin", "roles/resourcemanager.projectIamAdmin"]),
    )) == 0
    error_message = "Roles that administer access must be neither held nor grantable."
  }

  assert {
    condition = (
      startswith(google_project_iam_member.apply_grants.condition[0].expression, "api.getAttribute(\"iam.googleapis.com/modifiedGrantsByRole\", []).hasOnly([")
      && google_project_iam_member.apply_more_grants.condition[0].expression == "api.getAttribute(\"iam.googleapis.com/modifiedGrantsByRole\", []).hasOnly([\"roles/cloudsql.instanceUser\"])"
      && google_project_iam_member.apply_more_grants.role == google_project_iam_custom_role.project_grants.id
    )
    error_message = "Apply may change project access only under a condition."
  }

  assert {
    condition = alltrue([
      for m in concat(values(google_project_iam_member.apply), values(google_project_iam_member.read), [google_project_iam_member.delete, google_project_iam_member.apply_service_accounts, google_project_iam_member.apply_grants, google_project_iam_member.apply_more_grants, google_project_iam_member.census]) :
      m.project == "example-project-1"
    ])
    error_message = "No pipeline may have a project role in the bootstrap project."
  }
}

run "logs" {
  command = apply

  # Two logs and no more, each in a view of its own.
  assert {
    condition = { for name, view in google_logging_log_view.containers : name => view.filter } == {
      stderr = "SOURCE(\"projects/example-project-1\") AND LOG_ID(\"run.googleapis.com/stderr\")"
      stdout = "SOURCE(\"projects/example-project-1\") AND LOG_ID(\"run.googleapis.com/stdout\")"
    }
    error_message = "Only what the containers on Cloud Run print may be shown."
  }

  # No test with a pretended provider would notice: with a long name, the real one stops in the middle of an apply.
  assert {
    condition = alltrue([
      for view in values(google_logging_log_view.containers) : view.bucket == "_Default" && view.location == "global" && view.parent == "projects/example-project-1"
    ])
    error_message = "A view is named by its short names."
  }

  assert {
    condition = { for name, member in google_logging_log_view_iam_member.apply : name => [member.parent, member.location, member.bucket, member.name, member.role, member.member] } == {
      for name in ["stderr", "stdout"] : name => ["projects/example-project-1", "global", "_Default", "containers-${name}", "roles/logging.viewAccessor", "principalSet://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/github-actions/attribute.tier/apply"]
    }
    error_message = "Apply, and nobody else, may read the two views."
  }

  # On the project, these would open the audit log or every view.
  assert {
    condition = length(setintersection(
      toset(concat(local.apply_roles, local.grantable_roles, local.more_grantable_roles)),
      toset(["roles/logging.admin", "roles/logging.fieldAccessor", "roles/logging.linkViewer", "roles/logging.privateLogViewer", "roles/logging.viewAccessor", "roles/logging.viewer"]),
    )) == 0
    error_message = "No role on the project may read logs."
  }
}

run "cost" {
  command = apply

  assert {
    condition = (
      google_bigquery_dataset_iam_member.cost.member == "iamMember:principal://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/github-actions/subject/${var.cost_subject}"
      && google_bigquery_dataset_iam_member.cost.project == "example-bootstrap-1"
      && google_bigquery_dataset_iam_member.cost.dataset_id == "billing_export"
      && google_bigquery_dataset_iam_member.cost.role == google_project_iam_custom_role.cost.id
      && length(google_bigquery_dataset_iam_member.cost.condition) == 0
    )
    error_message = "One literal subject may read one dataset."
  }

  assert {
    condition = (
      google_project_iam_custom_role.cost.permissions == toset(["bigquery.tables.get", "bigquery.tables.getData", "bigquery.tables.list"])
      && google_project_iam_custom_role.cost.project == "example-bootstrap-1"
    )
    error_message = "The cost role may list and read tables, and nothing else. It may not run a query."
  }

  assert {
    condition = (
      google_bigquery_dataset.billing_export.project == "example-bootstrap-1"
      && google_bigquery_dataset.billing_export.location == "europe-west2"
      && !google_bigquery_dataset.billing_export.delete_contents_on_destroy
      && google_bigquery_dataset.billing_export.default_table_expiration_ms == null
      && google_bigquery_dataset.billing_export.default_partition_expiration_ms == null
      && length(google_bigquery_dataset.billing_export.default_encryption_configuration) == 0
    )
    error_message = "The costs must lie where no pipeline has a project role, and stay."
  }

  # Google's export account becomes an owner that Terraform does not know. Whatever sets the whole access list takes that
  # away, and the export stops without a word.
  assert {
    condition = google_bigquery_dataset.billing_export.dataset_id == "billing_export" && alltrue([
      for file in fileset(".", "*.tf") : !can(regex("(?m)^[^#]*(google_bigquery_dataset_(access|iam_policy|iam_binding)|\\baccess\\s*[{=])", file(file)))
    ])
    error_message = "Nothing may set the whole access list of the dataset."
  }

  # No role in any project, no tier, no state.
  assert {
    condition = alltrue([
      for m in concat(
        [for m in concat(values(google_project_iam_member.apply), values(google_project_iam_member.read), [google_project_iam_member.delete, google_project_iam_member.apply_service_accounts, google_project_iam_member.apply_grants, google_project_iam_member.apply_more_grants, google_project_iam_member.census]) : m.member],
        [for m in values(google_logging_log_view_iam_member.apply) : m.member],
        flatten([for b in jsondecode(google_storage_bucket_iam_policy.state.policy_data).bindings : b.members]),
      ) : !strcontains(m, "environment:cost")
    ])
    error_message = "The cost identity must have no role in a project and no right to any state."
  }

  assert {
    condition     = jsondecode(file("../cost.json")) == { cloud-labs = { cost = var.cost_subject } } && contains(output.trusted_subjects, var.cost_subject) && length(output.trusted_subjects) == 16
    error_message = "cost.json holds one subject, and the pool trusts that one and the 15."
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

run "github_secrets" {
  command = apply

  assert {
    condition = output.github_secrets == {
      cloud = "gcp"
      repos = {
        for repo, id in var.repo_ids : repo => merge({
          repository = {
            GCP_PROJECT_ID                 = "example-project-1"
            GCP_PROJECT_NUMBER             = "210987654321"
            GCP_STATE_BUCKET               = "tfstate-0a1b2c3d"
            GCP_WORKLOAD_IDENTITY_PROVIDER = google_iam_workload_identity_pool_provider.github.name
          }
          production      = {}
          nightly-destroy = {}
        }, { for name in ["cost"] : name => { GCP_COST_PROJECT_ID = "example-bootstrap-1" } if repo == "cloud-labs" })
      }
    }
    error_message = "Every repo gets the provider, the project it deploys into and the state bucket, and only cloud-labs the place of the costs."
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
