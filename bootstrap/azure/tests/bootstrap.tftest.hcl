# Runs against mocked providers: no credentials, nothing is created.

mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      object_id = "00000000-0000-0000-0000-00000000000a"
      tenant_id = "00000000-0000-0000-0000-00000000000b"
    }
  }
  mock_resource "azurerm_storage_account" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-github-bootstrap/providers/Microsoft.Storage/storageAccounts/tfstate0a1b2c3d" }
  }
  mock_resource "azurerm_resource_group" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/mock" }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-github-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mock"
      principal_id = "00000000-0000-0000-0000-00000000000c"
    }
  }
  mock_resource "azurerm_role_definition" {
    defaults = { role_definition_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Authorization/roleDefinitions/00000000-0000-0000-0000-00000000000d" }
  }
}

# The cost identity and its role have ids of their own, so that the tests can tell them apart from the others.
override_resource {
  target = azurerm_user_assigned_identity.cost
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-github-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/cost"
    principal_id = "00000000-0000-0000-0000-00000000000e"
  }
}

override_resource {
  target = azurerm_role_definition.cost
  values = { role_definition_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Authorization/roleDefinitions/00000000-0000-0000-0000-00000000000f" }
}

# So has the census role, and so has the one identity that may hold it.
override_resource {
  target = azurerm_role_definition.census
  values = { role_definition_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Authorization/roleDefinitions/00000000-0000-0000-0000-000000000010" }
}

override_resource {
  target = azurerm_user_assigned_identity.ci["cloud-labs/destroy"]
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-github-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/destroy"
    principal_id = "00000000-0000-0000-0000-000000000011"
    client_id    = "00000000-0000-0000-0000-000000000012"
  }
}

mock_provider "random" {
  mock_resource "random_id" {
    defaults = { hex = "0a1b2c3d" }
  }
}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"

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
    condition = { for key, c in azurerm_federated_identity_credential.ci : key => c.subject } == merge([
      for repo, id in var.repo_ids : { for tier, suffix in var.suffixes : "${repo}/${tier}" => "repo:oplf-svg@228823995/${repo}@${id}:${suffix}" }
    ]...)
    error_message = "Every identity must trust exactly one literal subject, for its own repo and tier."
  }

  assert {
    condition     = length(azurerm_user_assigned_identity.ci) == 15 && length(azurerm_federated_identity_credential.ci) == 15
    error_message = "Five repos with three tiers each make 15 identities with one credential each."
  }

  assert {
    condition = alltrue([
      for c in azurerm_federated_identity_credential.ci :
      c.issuer == "https://token.actions.githubusercontent.com" && c.audience == tolist(["api://AzureADTokenExchange"]) && !strcontains(c.subject, "*")
    ])
    error_message = "Credentials must use GitHub's issuer, the Entra audience and no wildcards."
  }

  assert {
    condition     = alltrue([for c in azurerm_federated_identity_credential.ci : can(regex(":environment:(plan|production|nightly-destroy):ref:refs/heads/main$", c.subject))])
    error_message = "Only jobs in one of the three environments and on main may be trusted, so never a pull request."
  }

  assert {
    condition     = { for key, i in azurerm_user_assigned_identity.ci : key => i.name } == { for key in keys(azurerm_user_assigned_identity.ci) : key => "id-gha-${replace(key, "/", "-")}" }
    error_message = "Each identity must be named after its own repo and tier."
  }
}

run "permissions" {
  command = apply

  assert {
    condition     = azurerm_role_definition.plan.permissions[0].actions == tolist(["*/read"])
    error_message = "The plan role may only read."
  }

  assert {
    condition     = azurerm_role_definition.destroy.permissions[0].actions == tolist(["*/read", "*/delete"])
    error_message = "The destroy role may only read and delete."
  }

  assert {
    condition     = contains(azurerm_role_definition.destroy.permissions[0].not_actions, "Microsoft.Resources/subscriptions/resourceGroups/delete")
    error_message = "The destroy role must not delete the resource group, because its roles are assigned there."
  }

  assert {
    condition = alltrue([
      for r in [azurerm_role_definition.plan, azurerm_role_definition.destroy] : alltrue([
        for a in [
          "Microsoft.Consumption/*",
          "Microsoft.DocumentDB/databaseAccounts/readonlykeys/read",
          "Microsoft.Insights/eventtypes/*",
          "Microsoft.Insights/logs/*",
          "Microsoft.OperationalInsights/workspaces/query/*",
          "Microsoft.OperationalInsights/workspaces/sharedKeys/read",
          "Microsoft.Web/sites/config/web/connectionstrings/read",
          "Microsoft.Web/sites/functions/masterkey/read",
          "Microsoft.Web/sites/hostruntime/*",
        ] : contains(r.permissions[0].not_actions, a)
      ])
    ])
    error_message = "Plan and destroy must not read keys, settings, logs or costs."
  }

  assert {
    condition = alltrue([
      for r in [azurerm_role_definition.plan, azurerm_role_definition.apply, azurerm_role_definition.destroy, azurerm_role_definition.register, azurerm_role_definition.cost, azurerm_role_definition.census] : alltrue([
        for a in concat(r.permissions[0].actions, r.permissions[0].not_actions) : length(regexall("[*]", a)) <= 1
      ])
    ])
    error_message = "Azure allows one wildcard in an action."
  }

  assert {
    condition = (
      azurerm_role_definition.apply.permissions[0].actions == tolist(["*"])
      && alltrue([
        for a in ["Microsoft.Authorization/*/Delete", "Microsoft.Authorization/*/Write", "Microsoft.Authorization/elevateAccess/Action", "Microsoft.Resources/subscriptions/resourceGroups/delete"] :
        contains(azurerm_role_definition.apply.permissions[0].not_actions, a)
      ])
      && alltrue([for a in azurerm_role_assignment.apply : a.role_definition_id == azurerm_role_definition.apply.role_definition_resource_id])
    )
    error_message = "Apply is Contributor without the right to delete the resource group."
  }

  assert {
    condition     = length(azurerm_role_assignment.plan) == 5 && length(azurerm_role_assignment.apply) == 5 && length(azurerm_role_assignment.destroy) == 5
    error_message = "Each repo has one assignment per tier on its own resource group."
  }

  assert {
    condition = alltrue([
      for a in azurerm_role_assignment.apply_grants :
      a.condition_version == "2.0"
      && strcontains(a.condition, "!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'})")
      && strcontains(a.condition, "!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'})")
      && length(a.condition) < 8192
      && !strcontains(a.condition, "\n")
    ])
    error_message = "Apply may grant roles only under a condition that covers adding and removing."
  }

  # Owner, Contributor, Reader, User Access Administrator, RBAC Administrator, Key Vault Data Access Administrator.
  assert {
    condition = alltrue([
      for id in ["8e3af657-a8ff-443c-a75c-2fe8c4bcb635", "b24988ac-6180-42a0-ab88-20f7382dd24c", "acdd72a7-3385-48ef-bd42-f606fba81ae7", "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9", "f58310d9-a9f6-439a-9e8d-f62e7b41a168", "8b54135c-b56d-4d72-a534-26097cfdc8d8"] :
      alltrue([for a in azurerm_role_assignment.apply_grants : !strcontains(a.condition, id)])
    ])
    error_message = "Roles that administer access, and the pipelines' own roles, must not be grantable."
  }

  assert {
    condition     = alltrue([for a in azurerm_role_assignment.destroy : strcontains(a.condition, "roleAssignments/delete") && !strcontains(a.condition, "roleAssignments/write")])
    error_message = "Destroy may remove only the grants that apply could have made."
  }
}

run "models" {
  command = apply

  # Names from Microsoft's reference of rights.
  assert {
    condition = alltrue([
      for a in [
        "Microsoft.CognitiveServices/accounts/write", "Microsoft.CognitiveServices/accounts/deployments/write", "Microsoft.CognitiveServices/accounts/listKeys/action", "Microsoft.CognitiveServices/accounts/regenerateKey/action",
        "Microsoft.MachineLearningServices/workspaces/write", "Microsoft.MachineLearningServices/workspaces/onlineEndpoints/write", "Microsoft.MachineLearningServices/workspaces/listKeys/action",
        "Microsoft.Marketplace/offerTypes/publishers/offers/plans/agreements/write", "Microsoft.MarketplaceOrdering/agreements/offers/plans/sign/action", "Microsoft.MarketplaceOrdering/offertypes/publishers/offers/plans/agreements/write",
      ] :
      anytrue([for n in azurerm_role_definition.apply.permissions[0].not_actions : can(regex("^${replace(replace(n, ".", "[.]"), "*", ".*")}$", a))])
    ])
    error_message = "Apply must not set up a model, read its keys or accept terms."
  }

  # Written out again here on purpose. What is not registered cannot be used, and some providers sell models too.
  assert {
    condition = toset(azurerm_role_definition.register.permissions[0].actions) == toset(concat(
      [for name in ["AlertsManagement", "App", "Compute", "ContainerService", "DBforPostgreSQL", "EventHub", "Insights", "ManagedIdentity", "Network", "OperationalInsights", "Storage", "Web"] : "Microsoft.${name}/register/action"],
      ["Microsoft.Resources/subscriptions/providers/read"],
    ))
    error_message = "Apply may register twelve providers and no other."
  }

  # No other role lets a pipeline register something: the one for its own group cannot, and neither can those that it may give.
  assert {
    condition = alltrue([
      for r in [azurerm_role_definition.plan, azurerm_role_definition.destroy, azurerm_role_definition.cost, azurerm_role_definition.census] :
      !anytrue([for a in r.permissions[0].actions : can(regex("register|/action$|^[*]$", a)) && a != "Microsoft.CostManagement/query/action"])
    ])
    error_message = "Only apply may register a provider."
  }

  # And nothing else goes with that.
  assert {
    condition = alltrue([
      for a in ["Microsoft.App/containerApps/write", "Microsoft.ContainerRegistry/registries/write", "Microsoft.ContainerService/managedClusters/write", "Microsoft.DBforPostgreSQL/flexibleServers/write", "Microsoft.EventHub/namespaces/write", "Microsoft.ManagedIdentity/userAssignedIdentities/write", "Microsoft.Web/staticSites/write"] :
      !anytrue([for n in azurerm_role_definition.apply.permissions[0].not_actions : can(regex("^${replace(replace(n, ".", "[.]"), "*", ".*")}$", a))])
    ])
    error_message = "Apply must still be able to set up containers, databases, clusters and sites."
  }
}

run "census" {
  command = apply

  assert {
    condition = (
      azurerm_role_definition.census.permissions[0].actions == tolist(["Microsoft.Resources/subscriptions/resourceGroups/read"])
      && length(azurerm_role_definition.census.permissions) == 1
      && try(length(azurerm_role_definition.census.permissions[0].data_actions), 0) == 0
      && azurerm_role_definition.census.scope == "/subscriptions/00000000-0000-0000-0000-000000000000"
    )
    error_message = "The census role may see which resource groups there are, and nothing that is in them."
  }

  # The subject is written out, so that another identity in that place fails the test.
  assert {
    condition = (
      azurerm_role_assignment.census.scope == "/subscriptions/00000000-0000-0000-0000-000000000000"
      && azurerm_role_assignment.census.role_definition_id == azurerm_role_definition.census.role_definition_resource_id
      && [for key, i in azurerm_user_assigned_identity.ci : azurerm_federated_identity_credential.ci[key].subject if i.principal_id == azurerm_role_assignment.census.principal_id] == ["repo:oplf-svg@228823995/cloud-labs@1469385611:environment:nightly-destroy:ref:refs/heads/main"]
    )
    error_message = "Only the destroy identity of cloud-labs may see the other resource groups."
  }

  # Nobody else holds that role, and that identity has nothing else outside its own group.
  assert {
    condition = alltrue([
      for a in concat(values(azurerm_role_assignment.plan), values(azurerm_role_assignment.apply), values(azurerm_role_assignment.apply_grants), values(azurerm_role_assignment.apply_register), values(azurerm_role_assignment.destroy), values(azurerm_role_assignment.state), [azurerm_role_assignment.cost]) :
      a.role_definition_id != azurerm_role_definition.census.role_definition_resource_id
      && (a.principal_id != azurerm_role_assignment.census.principal_id || a.scope != azurerm_role_assignment.census.scope)
    ])
    error_message = "The census role must be in one assignment only, and its identity in no other one on the subscription."
  }
}

run "cost" {
  command = apply

  assert {
    condition = (
      azurerm_federated_identity_credential.cost.subject == var.cost_subject
      && azurerm_federated_identity_credential.cost.issuer == "https://token.actions.githubusercontent.com"
      && azurerm_federated_identity_credential.cost.audience == tolist(["api://AzureADTokenExchange"])
      && azurerm_federated_identity_credential.cost.user_assigned_identity_id == azurerm_user_assigned_identity.cost.id
    )
    error_message = "The cost identity must trust one literal subject, of cloud-labs, in an environment of its own, on main."
  }

  assert {
    condition     = azurerm_user_assigned_identity.cost.name == "id-gha-cloud-labs-cost" && azurerm_user_assigned_identity.cost.resource_group_name == "rg-github-bootstrap"
    error_message = "The cost identity must lie where no pipeline has any rights."
  }

  assert {
    condition = (
      toset(azurerm_role_definition.cost.permissions[0].actions) == toset(["Microsoft.CostManagement/query/action", "Microsoft.CostManagement/query/read"])
      && length(azurerm_role_definition.cost.permissions) == 1
      && try(length(azurerm_role_definition.cost.permissions[0].data_actions), 0) == 0
    )
    error_message = "The cost role may ask what something has cost, and nothing else."
  }

  # The identity is in one assignment, with that role.
  assert {
    condition = (
      azurerm_role_assignment.cost.scope == "/subscriptions/00000000-0000-0000-0000-000000000000"
      && azurerm_role_assignment.cost.role_definition_id == azurerm_role_definition.cost.role_definition_resource_id
      && azurerm_role_assignment.cost.principal_id == azurerm_user_assigned_identity.cost.principal_id
      && length([
        for a in concat(values(azurerm_role_assignment.plan), values(azurerm_role_assignment.apply), values(azurerm_role_assignment.apply_grants), values(azurerm_role_assignment.apply_register), values(azurerm_role_assignment.destroy), values(azurerm_role_assignment.state)) :
        a if a.principal_id == azurerm_user_assigned_identity.cost.principal_id || a.role_definition_id == azurerm_role_definition.cost.role_definition_resource_id
      ]) == 0
      && !contains(keys(azurerm_user_assigned_identity.ci), "cloud-labs/cost")
    )
    error_message = "The cost identity must have its own role and no other, and no right to any state."
  }

  # Nothing else may hold the cost role or stand in its place.
  assert {
    condition     = jsondecode(file("../cost.json")) == { cloud-labs = { cost = var.cost_subject } } && contains(output.trusted_subjects, var.cost_subject) && length(output.trusted_subjects) == 16
    error_message = "cost.json holds one subject, and the subscription trusts that one and the 15."
  }
}

run "state" {
  command = apply

  assert {
    condition = (
      !azurerm_storage_account.state.allow_nested_items_to_be_public
      && !azurerm_storage_account.state.shared_access_key_enabled
      && !azurerm_storage_account.state.local_user_enabled
      && azurerm_storage_account.state.https_traffic_only_enabled
      && azurerm_storage_account.state.min_tls_version == "TLS1_2"
      && azurerm_storage_account.state.blob_properties[0].versioning_enabled
    )
    error_message = "The state account must block public access and keys, require TLS 1.2 and keep versions."
  }

  assert {
    condition     = alltrue([for c in azurerm_storage_container.state : c.container_access_type == "private"])
    error_message = "Containers must be private."
  }

  assert {
    condition     = toset(keys(azurerm_storage_container.state)) == toset(concat(keys(var.repo_ids), ["bootstrap"]))
    error_message = "One container per repo, plus one for this stack."
  }

  assert {
    condition = alltrue([
      for key, a in azurerm_role_assignment.state :
      endswith(a.scope, "/blobServices/default/containers/${split("/", key)[0]}")
      && a.role_definition_name == (endswith(key, "/plan") ? "Storage Blob Data Reader" : "Storage Blob Data Contributor")
    ])
    error_message = "An identity may only reach its own repo's container, and plan may only read it."
  }

  assert {
    condition     = azurerm_management_lock.bootstrap[0].lock_level == "CanNotDelete"
    error_message = "The bootstrap group must be locked against deletion."
  }
}

run "github_secrets" {
  command = apply

  assert {
    condition = output.github_secrets == {
      cloud = "azure"
      repos = {
        for repo, id in var.repo_ids : repo => merge({
          repository = {
            AZURE_CLIENT_ID       = azurerm_user_assigned_identity.ci["${repo}/plan"].client_id
            AZURE_STATE_ACCOUNT   = "tfstate0a1b2c3d"
            AZURE_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"
            AZURE_TENANT_ID       = "00000000-0000-0000-0000-00000000000b"
          }
          production      = { AZURE_CLIENT_ID = azurerm_user_assigned_identity.ci["${repo}/apply"].client_id }
          nightly-destroy = { AZURE_CLIENT_ID = azurerm_user_assigned_identity.ci["${repo}/destroy"].client_id }
        }, { for name in ["cost"] : name => { AZURE_CLIENT_ID = azurerm_user_assigned_identity.cost.client_id } if repo == "cloud-labs" })
      }
    }
    error_message = "Each environment must get its own identity, other jobs the plan identity, and only cloud-labs the cost identity."
  }

  assert {
    condition     = length(distinct(concat([for identity in azurerm_user_assigned_identity.ci : identity.client_id], [azurerm_user_assigned_identity.cost.client_id]))) == 16
    error_message = "The comparison above needs 16 different identities."
  }
}

run "rejects_a_wrong_subscription_id" {
  command         = plan
  expect_failures = [var.subscription_id]

  variables {
    subscription_id = "my-subscription"
  }
}

run "rejects_wildcard_extras" {
  command         = plan
  expect_failures = [var.plan_extra, var.destroy_extra]

  variables {
    plan_extra    = ["Microsoft.Web/*"]
    destroy_extra = ["Microsoft.Authorization/roleAssignments/write"]
  }
}
