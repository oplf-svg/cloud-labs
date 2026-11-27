# Free: 100 GB a month, and no way to pay for more. When that is used up, the site stops until the next month.
resource "azapi_resource" "site" {
  type      = "Microsoft.Web/staticSites@2024-11-01"
  name      = "cloud-labs-site"
  parent_id = "/subscriptions/${var.subscription_id}/resourceGroups/rg-cloud-labs"

  # Where Azure keeps the settings. There is no London to choose, and the files are served from everywhere.
  location = "centralus"

  body = {
    sku = {
      name = "Free"
      tier = "Free"
    }
    properties = {
      allowConfigFileUpdates   = true
      stagingEnvironmentPolicy = "Disabled"
    }
  }

  tags = {
    managed-by = "terraform"
    stack      = "site"
  }

  # Nothing else is read back, so nothing else ends up in the state.
  response_export_values = {
    host = "properties.defaultHostname"
  }
}
