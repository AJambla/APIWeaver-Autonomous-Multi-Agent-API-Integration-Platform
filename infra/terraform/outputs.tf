output "vm_public_ip" {
  description = "Public IP address of the APIWeaver host VM"
  value       = azurerm_public_ip.vm_ip.ip_address
}

output "postgres_fqdn" {
  description = "Fully qualified domain name of the PostgreSQL Flexible Server"
  value       = azurerm_postgresql_flexible_server.postgres.fqdn
}

output "postgres_admin_username" {
  description = "PostgreSQL administrator login username"
  value       = var.db_admin_username
}

output "postgres_admin_password" {
  description = "PostgreSQL administrator login password"
  value       = azurerm_postgresql_flexible_server.postgres.administrator_password
  sensitive   = true
}

output "storage_account_name" {
  description = "Name of the Azure Storage Account"
  value       = azurerm_storage_account.sa.name
}

output "artifacts_container_name" {
  description = "Name of the artifacts blob container"
  value       = azurerm_storage_container.artifacts.name
}

output "static_web_app_url" {
  description = "Default URL for the Azure Static Web App frontend"
  value       = "https://${azurerm_static_web_app.frontend.default_host_name}"
}

output "static_web_app_api_key" {
  description = "Deployment token for Azure Static Web Apps (Set as AZURE_STATIC_WEB_APPS_API_TOKEN in GitHub Secrets)"
  value       = azurerm_static_web_app.frontend.api_key
  sensitive   = true
}

output "ssh_private_key" {
  description = "Auto-generated private key for SSH access (if no key was provided)"
  value       = var.ssh_public_key == "" ? tls_private_key.vm_ssh[0].private_key_pem : "User-provided key"
  sensitive   = true
}
