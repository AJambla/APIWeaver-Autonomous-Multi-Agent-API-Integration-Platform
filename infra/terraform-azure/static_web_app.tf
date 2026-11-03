# Azure Static Web Apps: Hosts Frontend React SPA ($0 Free Tier)
# Provides automated global edge CDN, TLS certificates, and seamless GitHub Actions deployments.
resource "azurerm_static_web_app" "frontend" {
  name                = "swa-${var.app_name}-${var.environment}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = "centralindia"
  sku_tier            = "Free"
  sku_size            = "Free"

  tags = azurerm_resource_group.rg.tags
}
