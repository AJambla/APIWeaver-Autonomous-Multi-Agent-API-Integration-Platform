# Azure Storage Account (Name must be unique, lowercase alphanumeric only)
resource "azurerm_storage_account" "sa" {
  name                     = "st${replace(var.app_name, "-", "")}${random_id.storage_suffix.hex}"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"

  tags = azurerm_resource_group.rg.tags
}

# Artifacts Container: Stores generated SDK ZIP bundles, export packages
resource "azurerm_storage_container" "artifacts" {
  name                  = "artifacts"
  storage_account_id    = azurerm_storage_account.sa.id
  container_access_type = "private"
}

# Uploads Container: Stores raw uploaded OpenAPI/Swagger specs and documents
resource "azurerm_storage_container" "uploads" {
  name                  = "uploads"
  storage_account_id    = azurerm_storage_account.sa.id
  container_access_type = "private"
}

# Lifecycle Management: Auto-purge transient generated SDK packages after 14 days
resource "azurerm_storage_management_policy" "lifecycle" {
  storage_account_id = azurerm_storage_account.sa.id

  rule {
    name    = "purge-old-transient-artifacts"
    enabled = true

    filters {
      prefix_match = ["artifacts/"]
      blob_types   = ["blockBlob"]
    }

    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = 14
      }
    }
  }
}
