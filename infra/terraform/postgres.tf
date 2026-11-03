# Private DNS Zone required for PostgreSQL Flexible Server inside VNet
resource "azurerm_private_dns_zone" "postgres" {
  name                = "${var.app_name}-${var.environment}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.rg.name

  tags = azurerm_resource_group.rg.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "link-postgres-vnet"
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.vnet.id
  resource_group_name   = azurerm_resource_group.rg.name
}

# PostgreSQL 16 Flexible Server (Burstable B1ms: 1 vCPU, 2 GB RAM - Free Tier on Azure for Students)
resource "azurerm_postgresql_flexible_server" "postgres" {
  name                   = "psql-${var.app_name}-${var.environment}-${random_id.storage_suffix.hex}"
  resource_group_name    = azurerm_resource_group.rg.name
  location               = azurerm_resource_group.rg.location
  version                = "16"
  delegated_subnet_id    = azurerm_subnet.db.id
  private_dns_zone_id    = azurerm_private_dns_zone.postgres.id
  administrator_login    = var.db_admin_username
  administrator_password = var.db_admin_password != "" ? var.db_admin_password : random_password.db_password.result

  sku_name   = "B_Standard_B1ms"
  storage_mb = 32768

  backup_retention_days = 7
  zone                  = "1"

  tags = azurerm_resource_group.rg.tags

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

resource "azurerm_postgresql_flexible_server_database" "apiweaver" {
  name      = var.db_name
  server_id = azurerm_postgresql_flexible_server.postgres.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
