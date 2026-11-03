resource "azurerm_resource_group" "rg" {
  name     = "rg-${var.app_name}-${var.environment}"
  location = var.azure_region

  tags = {
    Project     = "APIWeaver"
    Environment = var.environment
    ManagedBy   = "Terraform"
    Plan        = "AzureForStudents"
  }
}

resource "random_id" "storage_suffix" {
  byte_length = 3
}

resource "random_password" "db_password" {
  length           = 24
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "tls_private_key" "vm_ssh" {
  count     = var.ssh_public_key == "" ? 1 : 0
  algorithm = "ED25519"
}
