# Azure Static Web Apps: Hosts Frontend React SPA ($0 Free Tier)
# Control plane metadata resides in East Asia (closest to India), while static assets
# are automatically distributed to Microsoft's global edge network with POPs in Mumbai, Delhi & Chennai.
resource "azurerm_static_web_app" "frontend" {
  name                = "swa-${var.app_name}-${var.environment}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = "eastasia"
  sku_tier            = "Free"
  sku_size            = "Free"

  tags = azurerm_resource_group.rg.tags
}
