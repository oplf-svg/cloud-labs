locals {
  # Everything in this file is granted on project_id. No pipeline has a project role where the
  # trust, the state and the costs are.

  # Deploy rights, service by service. Left out on purpose: the basic roles, roles that can buy
  # commitments (Compute Admin, BigQuery Admin, Vertex AI Admin), roles that can run Cloud Build
  # as the default service account (Dataflow), roles that can change the trust or create keys, and
  # roles that can turn services on or off (Monitoring Editor is one). Which ones are on stands in
  # services.json, and run.sh turns them on: what is off cannot be used, and what is turned off
  # cannot be asked about.
  apply_roles = [
    "roles/aiplatform.user",
    "roles/apigateway.admin",
    "roles/artifactregistry.admin",
    "roles/bigquery.dataOwner",
    "roles/bigquery.jobUser",
    "roles/certificatemanager.editor",
    "roles/cloudfunctions.admin",
    "roles/cloudscheduler.admin",
    "roles/cloudsql.admin",
    "roles/cloudtasks.admin",
    "roles/compute.instanceAdmin.v1",
    "roles/compute.loadBalancerAdmin",
    "roles/compute.networkAdmin",
    "roles/compute.securityAdmin",
    "roles/container.admin",
    "roles/datastore.owner",
    "roles/dns.admin",
    "roles/eventarc.admin",
    "roles/iam.serviceAccountUser",
    "roles/logging.configWriter",
    "roles/monitoring.alertPolicyEditor",
    "roles/monitoring.dashboardEditor",
    "roles/monitoring.notificationChannelEditor",
    "roles/monitoring.uptimeCheckConfigEditor",
    "roles/monitoring.viewer",
    "roles/pubsub.admin",
    "roles/redis.admin",
    "roles/run.admin",
    "roles/secretmanager.admin",
    "roles/servicenetworking.networksAdmin",
    "roles/storage.admin",
    "roles/vpcaccess.admin",
    "roles/workflows.admin",
  ]

  # The only project-level roles a pipeline may grant or revoke. They are ones that cannot be
  # granted on a single resource. Anything else belongs on the resource itself.
  # Google accepts at most ten here, and no second list joined with || or &&.
  grantable_roles = [
    "roles/aiplatform.user",
    "roles/bigquery.jobUser",
    "roles/cloudsql.client",
    "roles/cloudtrace.agent",
    "roles/container.defaultNodeServiceAccount",
    "roles/datastore.user",
    "roles/eventarc.eventReceiver",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/workflows.invoker",
  ]

  only_grantable = "api.getAttribute(\"iam.googleapis.com/modifiedGrantsByRole\", []).hasOnly(${jsonencode(local.grantable_roles)})"

  # The eleventh has a grant of its own, so one request can only change one of the two lists.
  more_grantable_roles = ["roles/cloudsql.instanceUser"]

  only_more_grantable = "api.getAttribute(\"iam.googleapis.com/modifiedGrantsByRole\", []).hasOnly(${jsonencode(local.more_grantable_roles)})"

  # Service => resource types. Plan reads their configuration. Destroy can also delete them.
  resource_types = {
    aiplatform         = ["batchPredictionJobs", "customJobs", "datasets", "deploymentResourcePools", "endpoints", "featureGroups", "featureOnlineStores", "featureViews", "indexEndpoints", "indexes", "models", "pipelineJobs", "reasoningEngines", "schedules", "tensorboards", "trainingPipelines"]
    apigateway         = ["apiconfigs", "apis", "gateways"]
    artifactregistry   = ["packages", "repositories", "tags", "versions"]
    bigquery           = ["datasets", "models", "routines", "tables"]
    certificatemanager = ["certissuanceconfigs", "certmapentries", "certmaps", "certs", "dnsauthorizations", "trustconfigs"]
    cloudfunctions     = ["functions"]
    cloudkms           = ["cryptoKeyVersions", "cryptoKeys", "keyRings"]
    cloudscheduler     = ["jobs"]
    cloudsql           = ["backupRuns", "databases", "instances", "sslCerts", "users"]
    cloudtasks         = ["queues"]
    compute            = ["addresses", "autoscalers", "backendBuckets", "backendServices", "disks", "firewallPolicies", "firewalls", "forwardingRules", "globalAddresses", "globalForwardingRules", "globalNetworkEndpointGroups", "healthChecks", "images", "instanceGroupManagers", "instanceGroups", "instanceTemplates", "instances", "networkAttachments", "networkEndpointGroups", "networks", "regionBackendServices", "regionHealthChecks", "regionNetworkEndpointGroups", "regionSecurityPolicies", "regionSslCertificates", "regionTargetHttpProxies", "regionTargetHttpsProxies", "regionTargetTcpProxies", "regionUrlMaps", "resourcePolicies", "routers", "routes", "securityPolicies", "serviceAttachments", "snapshots", "sslCertificates", "sslPolicies", "subnetworks", "targetHttpProxies", "targetHttpsProxies", "targetInstances", "targetPools", "targetSslProxies", "targetTcpProxies", "urlMaps", "vpnGateways", "vpnTunnels"]
    container          = ["clusters"]
    datastore          = ["backupSchedules", "databases", "indexes", "schemas"]
    dns                = ["managedZones", "policies", "resourceRecordSets", "responsePolicies", "responsePolicyRules"]
    eventarc           = ["channels", "enrollments", "googleApiSources", "messageBuses", "pipelines", "triggers"]
    iam                = ["serviceAccounts"]
    logging            = ["buckets", "exclusions", "links", "logMetrics", "logScopes", "notificationRules", "sinks", "views"]
    monitoring         = ["alertPolicies", "dashboards", "groups", "metricDescriptors", "notificationChannels", "services", "slos", "uptimeCheckConfigs"]
    pubsub             = ["schemas", "snapshots", "subscriptions", "topics"]
    redis              = ["clusters", "instances"]
    run                = ["executions", "instances", "jobs", "revisions", "services", "workerpools"]
    secretmanager      = ["secrets"]
    vpcaccess          = ["connectors"]
    workflows          = ["workflows"]
  }

  types = flatten([for service, names in local.resource_types : [for name in names : "${service}.${name}"]])

  # Configuration only. Nothing here returns object, row, message, log or secret contents.
  read_permissions = toset(concat(
    flatten([for type in local.types : ["${type}.get", "${type}.getIamPolicy", "${type}.list"]]),
    [
      "apigateway.operations.get",
      "certificatemanager.operations.get",
      "cloudfunctions.operations.get",
      "compute.globalOperations.get",
      "compute.machineTypes.get",
      "compute.machineTypes.list",
      "compute.projects.get",
      "compute.regionOperations.get",
      "compute.regions.get",
      "compute.regions.list",
      "compute.zoneOperations.get",
      "compute.zones.get",
      "compute.zones.list",
      "container.operations.get",
      "datastore.databases.getMetadata",
      "datastore.operations.get",
      "dns.changes.get",
      "dns.projects.get",
      "eventarc.operations.get",
      "iam.roles.get",
      "iam.roles.list",
      "redis.operations.get",
      "resourcemanager.projects.get",
      "resourcemanager.projects.getIamPolicy",
      "run.operations.get",
      "secretmanager.versions.get",
      "secretmanager.versions.list",
      "servicenetworking.services.get",
      "serviceusage.services.get",
      "serviceusage.services.list",
      "serviceusage.services.use",
      "storage.buckets.get",
      "storage.buckets.getIamPolicy",
      "storage.buckets.list",
      "vpcaccess.operations.get",
      "workflows.operations.get",
    ],
    var.plan_extra,
  ))

  delete_permissions = toset(concat(
    [for type in local.types : "${type}.delete"],
    [
      "aiplatform.endpoints.undeploy",
      "aiplatform.indexEndpoints.undeploy",
      "cloudkms.cryptoKeyVersions.destroy",
      "compute.networks.removePeering",
      "pubsub.topics.detachSubscription",
      "secretmanager.versions.destroy",
      "servicenetworking.services.deleteConnection",
      "storage.buckets.delete",
      "storage.folders.delete",
      "storage.managedFolders.delete",
      "storage.objects.delete",
      # Needed next to the delete permission. On their own these three create nothing.
      "compute.networks.updatePolicy",
      "dns.changes.create",
      "storage.objects.list",
    ],
    var.destroy_extra,
  ))

  # Service accounts for workloads. No keys, no impersonation, no say over who may use them.
  service_account_permissions = toset([
    "iam.serviceAccounts.create",
    "iam.serviceAccounts.delete",
    "iam.serviceAccounts.disable",
    "iam.serviceAccounts.enable",
    "iam.serviceAccounts.get",
    "iam.serviceAccounts.getIamPolicy",
    "iam.serviceAccounts.list",
    "iam.serviceAccounts.undelete",
    "iam.serviceAccounts.update",
  ])

  # Only ever granted under the only_grantable condition.
  project_grant_permissions = toset([
    "resourcemanager.projects.get",
    "resourcemanager.projects.getIamPolicy",
    "resourcemanager.projects.setIamPolicy",
  ])

  offered = toset(data.google_iam_testable_permissions.project.permissions[*].name)
}

# One unknown name would make Google refuse a whole role, so keep only the names it offers.
data "google_iam_testable_permissions" "project" {
  full_resource_name = "//cloudresourcemanager.googleapis.com/projects/${var.project_id}"
  stages             = ["GA", "BETA"]
}

resource "google_project_iam_custom_role" "read" {
  project     = var.project_id
  role_id     = "ghaRead"
  title       = "GitHub Actions read"
  description = "Reads configuration. No data, logs or secret values."
  permissions = setintersection(local.read_permissions, local.offered)
}

resource "google_project_iam_custom_role" "delete" {
  project     = var.project_id
  role_id     = "ghaDelete"
  title       = "GitHub Actions delete"
  description = "Deletes resources. Cannot create them."
  permissions = setintersection(local.delete_permissions, local.offered)
}

resource "google_project_iam_custom_role" "service_accounts" {
  project     = var.project_id
  role_id     = "ghaServiceAccounts"
  title       = "GitHub Actions service accounts"
  description = "Manages service accounts for workloads. No keys and no impersonation."
  permissions = setintersection(local.service_account_permissions, local.offered)
}

resource "google_project_iam_custom_role" "project_grants" {
  project     = var.project_id
  role_id     = "ghaProjectGrants"
  title       = "GitHub Actions project grants"
  description = "Changes project access. Granted only under a condition that limits the roles."
  permissions = setintersection(local.project_grant_permissions, local.offered)
}

# A second opinion for the night run of cloud-labs: searches for what no list of a service shows. Google offers this one or
# refuses the role, so it does not go through local.offered: there it would vanish without a word.
resource "google_project_iam_custom_role" "census" {
  project     = var.project_id
  role_id     = "ghaCensus"
  title       = "GitHub Actions census"
  description = "Searches everything in the project. Only for the night run of cloud-labs."
  permissions = ["cloudasset.assets.searchAllResources"]
}

resource "google_project_iam_member" "census" {
  project = var.project_id
  role    = google_project_iam_custom_role.census.id
  member  = local.principal["cloud-labs/destroy"]

  depends_on = [google_iam_workload_identity_pool_provider.github]
}

resource "google_project_iam_member" "read" {
  for_each = toset(["plan", "destroy"])

  project = var.project_id
  role    = google_project_iam_custom_role.read.id
  member  = local.tier_principals[each.key]

  depends_on = [google_iam_workload_identity_pool_provider.github]
}

resource "google_project_iam_member" "delete" {
  project = var.project_id
  role    = google_project_iam_custom_role.delete.id
  member  = local.tier_principals["destroy"]

  depends_on = [google_iam_workload_identity_pool_provider.github]
}

resource "google_project_iam_member" "apply" {
  for_each = toset(concat(local.apply_roles, var.apply_extra))

  project = var.project_id
  role    = each.key
  member  = local.tier_principals["apply"]

  depends_on = [google_iam_workload_identity_pool_provider.github]
}

resource "google_project_iam_member" "apply_service_accounts" {
  project = var.project_id
  role    = google_project_iam_custom_role.service_accounts.id
  member  = local.tier_principals["apply"]

  depends_on = [google_iam_workload_identity_pool_provider.github]
}

resource "google_project_iam_member" "apply_grants" {
  project = var.project_id
  role    = google_project_iam_custom_role.project_grants.id
  member  = local.tier_principals["apply"]

  condition {
    title       = "only-workload-roles"
    description = "May grant or revoke a fixed list of roles. None of them administers access."
    expression  = local.only_grantable
  }

  depends_on = [google_iam_workload_identity_pool_provider.github]
}

resource "google_project_iam_member" "apply_more_grants" {
  project = var.project_id
  role    = google_project_iam_custom_role.project_grants.id
  member  = local.tier_principals["apply"]

  condition {
    title       = "only-database-sign-in"
    description = "May grant or revoke one role, with which a workload signs in to a database without a password."
    expression  = local.only_more_grantable
  }

  depends_on = [google_iam_workload_identity_pool_provider.github]
}

locals {
  # run.sh turns them on, and the night compares. Here only for the tests.
  services = jsondecode(file("${path.module}/services.json"))["deploy"]
}

# Sees which services are on, and has its calls counted against the project. Turns none on or off.
resource "google_project_iam_custom_role" "services" {
  project     = var.project_id
  role_id     = "ghaServices"
  title       = "GitHub Actions services"
  description = "Sees which services are on. Turns none on or off."
  permissions = ["serviceusage.services.get", "serviceusage.services.list", "serviceusage.services.use"]
}

resource "google_project_iam_member" "apply_services" {
  project = var.project_id
  role    = google_project_iam_custom_role.services.id
  member  = local.tier_principals["apply"]

  depends_on = [google_iam_workload_identity_pool_provider.github]
}
