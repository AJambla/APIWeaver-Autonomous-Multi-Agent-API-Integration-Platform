# The Single Host VM: Standard_B2als_v2 (AMD64 - 2 vCPU, 2 GB RAM)
# Runs Docker Compose (Nginx, FastAPI, Celery, Redis, and Docker Socket Proxy)
resource "azurerm_linux_virtual_machine" "host" {
  name                = "vm-${var.app_name}-${var.environment}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  size                = var.vm_size
  admin_username      = var.admin_username

  network_interface_ids = [
    azurerm_network_interface.vm_nic.id,
  ]

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.ssh_public_key != "" ? var.ssh_public_key : tls_private_key.vm_ssh[0].public_key_openssh
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = filebase64("${path.module}/cloud-init.yaml")

  # System-Assigned Managed Identity for passwordless Azure Blob Storage access
  identity {
    type = "SystemAssigned"
  }

  tags = azurerm_resource_group.rg.tags
}

# Grant VM's Managed Identity read/write access to the Azure Storage Account
resource "azurerm_role_assignment" "blob_contributor" {
  scope                = azurerm_storage_account.sa.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_virtual_machine.host.identity[0].principal_id
}

# Nightly Auto-Shutdown Schedule: Deallocates VM at midnight to save ~50% of student credits
resource "azurerm_dev_test_global_vm_shutdown_schedule" "auto_shutdown" {
  virtual_machine_id = azurerm_linux_virtual_machine.host.id
  location           = azurerm_resource_group.rg.location
  enabled            = var.auto_shutdown_enabled

  daily_recurrence_time = var.auto_shutdown_time
  timezone              = var.auto_shutdown_timezone

  notification_settings {
    enabled = false
  }

  tags = azurerm_resource_group.rg.tags
}
