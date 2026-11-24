# Against a stand-in for Azure. Nothing real is called.
mock_provider "azapi" {
  mock_resource "azapi_resource" {
    defaults = {
      output = { host = "example.azurestaticapps.net" }
    }
  }
}

variables {
  subscription_id = "11111111-2222-3333-4444-555555555555"
}

run "costs_nothing" {
  assert {
    condition     = azapi_resource.site.body.sku == { name = "Free", tier = "Free" }
    error_message = "Only the free plan has no overage charges."
  }
}

run "stays_in_the_group_of_this_repo" {
  command = plan

  assert {
    condition     = azapi_resource.site.parent_id == "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/rg-cloud-labs"
    error_message = "The pipeline has rights in one resource group only."
  }
}

run "serves_one_version_only" {
  command = plan

  assert {
    condition     = azapi_resource.site.body.properties.stagingEnvironmentPolicy == "Disabled"
    error_message = "Nothing but the approved version may be reachable."
  }
}

run "keeps_no_key_in_the_state" {
  command = plan

  assert {
    condition     = azapi_resource.site.response_export_values == { host = "properties.defaultHostname" }
    error_message = "Only the host name may be read back."
  }
}

run "refuses_another_kind_of_id" {
  command         = plan
  expect_failures = [var.subscription_id]

  variables {
    subscription_id = "my subscription"
  }
}
