locals {
  # Reads that return keys, tokens, settings, logs, query results or costs. They are ordinary control
  # plane reads, so "*/read" includes them. Taken from Microsoft's permission reference.
  no_contents = [
    "Microsoft.ApiManagement/service/tenants/keys/read",
    "Microsoft.ApiManagement/service/users/keys/read",
    "Microsoft.Automation/automationAccounts/jobs/output/read",
    "Microsoft.Automation/automationAccounts/jobs/streams/read",
    "Microsoft.Billing/*",
    "Microsoft.Consumption/*",
    "Microsoft.ContainerInstance/containerGroups/containers/buildlogs/read",
    "Microsoft.ContainerInstance/containerGroups/containers/logs/read",
    "Microsoft.CostManagement/*",
    "Microsoft.DBforMySQL/flexibleServers/logFiles/read",
    "Microsoft.DBforPostgreSQL/flexibleServers/logFiles/read",
    "Microsoft.DBforPostgreSQL/flexibleServers/queryTexts/read",
    "Microsoft.DataFactory/datafactories/runs/loginfo/read",
    "Microsoft.DocumentDB/databaseAccounts/readonlykeys/read",
    "Microsoft.Insights/components/api/read",
    "Microsoft.Insights/components/apiKeys/read",
    "Microsoft.Insights/components/events/*",
    "Microsoft.Insights/components/extendQueries/read",
    "Microsoft.Insights/components/getToken/read",
    "Microsoft.Insights/components/query/read",
    "Microsoft.Insights/eventtypes/*",
    "Microsoft.Insights/generateLiveToken/read",
    "Microsoft.Insights/logs/*",
    "Microsoft.Insights/webtests/getToken/read",
    "Microsoft.Logic/workflows/accessKeys/read",
    "Microsoft.Logic/workflows/runs/*",
    "Microsoft.Logic/workflows/triggers/histories/*",
    "Microsoft.MachineLearningServices/workspaces/datasets/*/read",
    "Microsoft.MachineLearningServices/workspaces/listNotebookAccessToken/read",
    "Microsoft.MachineLearningServices/workspaces/listNotebookKeys/read",
    "Microsoft.MachineLearningServices/workspaces/metadata/secrets/read",
    "Microsoft.Network/bastionHosts/getsessionrecordingsasurl/read",
    "Microsoft.Network/connections/sharedKey/read",
    "Microsoft.Network/vpnGateways/vpnConnections/vpnLinkConnections/sharedKeys/*",
    "Microsoft.NotificationHubs/namespaces/notificationHubs/vapidkeys/read",
    "Microsoft.OperationalInsights/workspaces/listKeys/read",
    "Microsoft.OperationalInsights/workspaces/query/*",
    "Microsoft.OperationalInsights/workspaces/sharedKeys/read",
    "Microsoft.OperationalInsights/workspaces/tables/query/*",
    "Microsoft.RecoveryServices/vaults/vaultTokens/read",
    "Microsoft.Resources/deploymentScripts/logs/read",
    "Microsoft.Sql/servers/databases/queryStore/queryTexts/read",
    "Microsoft.Web/sites/config/appsettings/read",
    "Microsoft.Web/sites/config/snapshots/read",
    "Microsoft.Web/sites/config/web/appsettings/read",
    "Microsoft.Web/sites/config/web/connectionstrings/read",
    "Microsoft.Web/sites/deployments/log/read",
    "Microsoft.Web/sites/functions/masterkey/read",
    "Microsoft.Web/sites/functions/token/read",
    "Microsoft.Web/sites/hostruntime/*",
    "Microsoft.Web/sites/instances/extensions/log/read",
    "Microsoft.Web/sites/instances/extensions/processes/read",
    "Microsoft.Web/sites/instances/processes/read",
    "Microsoft.Web/sites/processes/read",
    "Microsoft.Web/sites/publishxml/read",
    "Microsoft.Web/sites/slots/config/appsettings/read",
    "Microsoft.Web/sites/slots/config/snapshots/read",
    "Microsoft.Web/sites/slots/config/web/connectionstrings/read",
    "Microsoft.Web/sites/slots/deployments/log/read",
    "Microsoft.Web/sites/slots/instances/processes/read",
    "Microsoft.Web/sites/slots/processes/read",
    "Microsoft.Web/sites/triggeredwebjobs/history/read",
  ]

  # What the built-in Contributor role leaves out, apart from Blueprints, which Azure is retiring.
  not_contributor = [
    "Microsoft.Authorization/*/Delete",
    "Microsoft.Authorization/*/Write",
    "Microsoft.Authorization/elevateAccess/Action",
    "Microsoft.Compute/galleries/share/action",
    "Microsoft.Purview/consents/delete",
    "Microsoft.Purview/consents/write",
    "Microsoft.Resources/deploymentStacks/manageDenySetting/action",
    "Microsoft.Subscription/cancel/action",
    "Microsoft.Subscription/enable/action",
  ]

  # The only roles a pipeline may grant or revoke, and only for service principals. None of
  # them can assign roles. The pipelines' own roles are not listed, so they cannot be removed.
  grantable_roles = {
    "AcrPull"                                     = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
    "AcrPush"                                     = "8311e382-0749-4cb8-b61a-304f252e45ec"
    "App Configuration Data Reader"               = "516239f1-63e1-4d78-a4de-a74fb236a071"
    "Azure Event Hubs Data Owner"                 = "f526a384-b230-433a-b45c-95f59c4a2dec"
    "Azure Event Hubs Data Receiver"              = "a638d3c7-ab3a-418d-83e6-5f17a39d4fde"
    "Azure Event Hubs Data Sender"                = "2b629674-e913-4c01-ae53-ef4638d8f975"
    "Azure Kubernetes Service Cluster User Role"  = "4abbcc35-e782-43d8-92c5-2d3f1bd2253f"
    "Azure Kubernetes Service RBAC Cluster Admin" = "b1ff04bb-8a4e-4dc4-8eb5-8693973ce19b"
    "Azure Service Bus Data Owner"                = "090c5cfd-751d-490a-894a-3ce6f1109419"
    "Azure Service Bus Data Receiver"             = "4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0"
    "Azure Service Bus Data Sender"               = "69a216fc-b8fb-44d8-bc22-1f3c2cd27a39"
    "Cognitive Services OpenAI User"              = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
    "Cognitive Services User"                     = "a97b65f3-24c7-4388-baec-2e87135dc908"
    "EventGrid Data Sender"                       = "d5a91429-5739-47e2-a06b-3470a27159e7"
    "Key Vault Certificates Officer"              = "a4417e6f-fecd-4de8-b567-7b0420556985"
    "Key Vault Crypto Officer"                    = "14b46e9e-c2b7-41b4-b07b-48a6ebf60603"
    "Key Vault Crypto Service Encryption User"    = "e147488a-f6f5-4113-8e2d-b22465e65bf6"
    "Key Vault Crypto User"                       = "12338af0-0e69-4776-bea7-57ae8d297424"
    "Key Vault Secrets Officer"                   = "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
    "Key Vault Secrets User"                      = "4633458b-17de-408a-b874-0445c86b69e6"
    "Log Analytics Reader"                        = "73c42c96-874c-492b-b04d-ab87d138a893"
    "Managed Identity Operator"                   = "f1a07417-d97a-45cb-824c-7a7467783830"
    "Monitoring Metrics Publisher"                = "3913510d-42f4-4e42-8a64-420c390055eb"
    "Monitoring Reader"                           = "43d0d8ad-25c7-4714-9337-8ba259a9fe05"
    "Network Contributor"                         = "4d97b98b-1d4f-4787-a291-c67834d212e7"
    "Private DNS Zone Contributor"                = "b12aa53e-6015-4669-85d0-8515ebb3ae7f"
    "Search Index Data Contributor"               = "8ebe5a00-799e-43f5-93ac-243d3dce84a7"
    "Search Index Data Reader"                    = "1407120a-92aa-4202-b7e9-c0e197c71c8f"
    "Storage Blob Data Contributor"               = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
    "Storage Blob Data Owner"                     = "b7e6dc6d-f1e8-4753-8033-0f276bb0955b"
    "Storage Blob Data Reader"                    = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"
    "Storage Queue Data Contributor"              = "974c5e8b-45b9-4653-ba55-5f855dd0fb88"
    "Storage Queue Data Message Processor"        = "8a0f0c08-91a1-4084-bc3d-661d67233fed"
    "Storage Queue Data Message Sender"           = "c6a89b2d-59bc-44d0-9896-0f6e12d7b80a"
    "Storage Table Data Contributor"              = "0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3"
  }

  # One line each: Azure compares conditions as plain text.
  grantable_ids = join(", ", sort(values(local.grantable_roles)))

  only_grantable = {
    for action, source in { write = "Request", delete = "Resource" } : action => join("", [
      "((!(ActionMatches{'Microsoft.Authorization/roleAssignments/${action}'})) OR (",
      "@${source}[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${local.grantable_ids}}",
      " AND ",
      "@${source}[Microsoft.Authorization/roleAssignments:PrincipalType] ForAnyOfAnyValues:StringEqualsIgnoreCase {'ServicePrincipal'}",
      "))",
    ])
  }

  by_tier = {
    for tier in keys(local.subject_suffix) : tier => { for key, id in local.identities : key => id if id.tier == tier }
  }
}

# Read configuration, not data.
resource "azurerm_role_definition" "plan" {
  name              = "GitHub Actions plan"
  description       = "Reads the configuration of a resource group. No keys, logs or data."
  scope             = local.subscription
  assignable_scopes = [local.subscription]

  permissions {
    actions     = concat(["*/read"], var.plan_extra)
    not_actions = local.no_contents
  }
}

# Contributor, except that it cannot delete the resource group. That would delete every
# pipeline's rights along with it, because they are assigned there.
resource "azurerm_role_definition" "apply" {
  name              = "GitHub Actions apply"
  description       = "Contributor without the right to delete the resource group."
  scope             = local.subscription
  assignable_scopes = [local.subscription]

  permissions {
    actions     = ["*"]
    not_actions = concat(local.not_contributor, ["Microsoft.Resources/subscriptions/resourceGroups/delete"])
  }
}

# Read configuration and delete. Nothing that creates or changes a resource.
resource "azurerm_role_definition" "destroy" {
  name              = "GitHub Actions destroy"
  description       = "Reads and deletes inside a resource group. Cannot create, change, or delete the group itself."
  scope             = local.subscription
  assignable_scopes = [local.subscription]

  permissions {
    actions = concat(["*/read", "*/delete"], var.plan_extra, var.destroy_extra)
    not_actions = concat(local.no_contents, [
      "Microsoft.Authorization/locks/delete",
      "Microsoft.Authorization/policyAssignments/delete",
      "Microsoft.Authorization/policyDefinitions/delete",
      "Microsoft.Authorization/roleDefinitions/delete",
      "Microsoft.Resources/subscriptions/resourceGroups/delete",
    ])
  }
}

# Registering a resource provider is free and happens at subscription level, outside any group.
resource "azurerm_role_definition" "register" {
  name              = "GitHub Actions provider registration"
  description       = "Registers resource providers. No preview features."
  scope             = local.subscription
  assignable_scopes = [local.subscription]

  permissions {
    actions     = ["*/register/action", "Microsoft.Resources/subscriptions/providers/read"]
    not_actions = ["Microsoft.Features/*"]
  }
}

resource "azurerm_role_assignment" "plan" {
  for_each = local.by_tier.plan

  scope              = azurerm_resource_group.repo[each.value.repo].id
  role_definition_id = azurerm_role_definition.plan.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.ci[each.key].principal_id
  principal_type     = "ServicePrincipal"
}

# Cannot assign roles, and reaches only the repo's own resource group.
resource "azurerm_role_assignment" "apply" {
  for_each = local.by_tier.apply

  scope              = azurerm_resource_group.repo[each.value.repo].id
  role_definition_id = azurerm_role_definition.apply.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.ci[each.key].principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "apply_grants" {
  for_each = local.by_tier.apply

  scope                = azurerm_resource_group.repo[each.value.repo].id
  role_definition_name = "Role Based Access Control Administrator"
  principal_id         = azurerm_user_assigned_identity.ci[each.key].principal_id
  principal_type       = "ServicePrincipal"
  condition_version    = "2.0"
  condition            = "${local.only_grantable.write} AND ${local.only_grantable.delete}"
}

resource "azurerm_role_assignment" "apply_register" {
  for_each = local.by_tier.apply

  scope              = local.subscription
  role_definition_id = azurerm_role_definition.register.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.ci[each.key].principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "apply_extra" {
  for_each = {
    for pair in setproduct(keys(local.by_tier.apply), var.apply_extra) : "${pair[0]}/${pair[1]}" => {
      identity = pair[0]
      role     = pair[1]
    }
  }

  scope                = azurerm_resource_group.repo[local.identities[each.value.identity].repo].id
  role_definition_name = each.value.role
  principal_id         = azurerm_user_assigned_identity.ci[each.value.identity].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "destroy" {
  for_each = local.by_tier.destroy

  scope              = azurerm_resource_group.repo[each.value.repo].id
  role_definition_id = azurerm_role_definition.destroy.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.ci[each.key].principal_id
  principal_type     = "ServicePrincipal"
  condition_version  = "2.0"
  condition          = local.only_grantable.delete
}
