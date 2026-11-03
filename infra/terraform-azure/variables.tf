variable "app_name" {
  description = "Base application name used for resource naming"
  type        = string
  default     = "apiweaver"
}

variable "environment" {
  description = "Deployment environment (production, staging, dev)"
  type        = string
  default     = "production"
}

variable "azure_region" {
  description = "Target Azure region for all regional resources"
  type        = string
  default     = "centralindia"
}

variable "vm_size" {
  description = "Azure VM SKU size (Standard_B2als_v2 recommended for student plan: 2 vCPU, 2 GB RAM AMD64)"
  type        = string
  default     = "Standard_B2als_v2"
}

variable "admin_username" {
  description = "Administrator username for the Linux VM"
  type        = string
  default     = "azureuser"
}

variable "ssh_public_key" {
  description = "Optional SSH public key for direct VM access. If omitted, an ed25519 key will be generated."
  type        = string
  default     = ""
}

variable "db_name" {
  description = "PostgreSQL initial database name"
  type        = string
  default     = "apiweaver"
}

variable "db_admin_username" {
  description = "PostgreSQL administrator login username"
  type        = string
  default     = "apiweaver_admin"
}

variable "db_admin_password" {
  description = "PostgreSQL administrator password. If left blank, a random secure password will be generated."
  type        = string
  default     = ""
  sensitive   = true
}

variable "auto_shutdown_enabled" {
  description = "Whether to automatically shut down the VM nightly to save student credits"
  type        = bool
  default     = true
}

variable "auto_shutdown_time" {
  description = "24-hour time for nightly VM auto-shutdown (HHmm format)"
  type        = string
  default     = "0000"
}

variable "auto_shutdown_timezone" {
  description = "Timezone for VM auto-shutdown"
  type        = string
  default     = "India Standard Time"
}
