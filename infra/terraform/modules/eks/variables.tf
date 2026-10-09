variable "environment" {
  description = "Environment name"
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
}

variable "cluster_version" {
  description = "EKS cluster version"
  type        = string
  default     = "1.30"
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "private_subnets" {
  description = "Private subnet IDs"
  type        = list(string)
}

# No default on purpose: an omitted value must fail the plan rather than fall back to the
# documented 0.0.0.0/0 that `aws_eks_cluster` uses when the list is absent.
variable "public_access_cidrs" {
  description = <<-EOT
    CIDR blocks allowed to reach the public EKS API server endpoint (the operator/admin
    networks, as host routes or small prefixes). Must not be empty and must not contain
    0.0.0.0/0 or ::/0.
  EOT
  type        = list(string)

  validation {
    condition     = length(var.public_access_cidrs) > 0
    error_message = "Set public_access_cidrs to the admin networks that may reach the EKS API server; an empty list would mean 0.0.0.0/0."
  }

  validation {
    condition     = alltrue([for c in var.public_access_cidrs : c != "0.0.0.0/0" && c != "::/0"])
    error_message = "0.0.0.0/0 and ::/0 are refused: they would make the public API server endpoint reachable from any address."
  }
}

variable "s3_buckets" {
  description = "S3 bucket names for IRSA"
  type = object({
    uploads   = string
    artifacts = string
    backups   = string
  })
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}

variable "kube_proxy_version" {
  type    = string
  default = "v1.30.0"
}

variable "coredns_version" {
  type    = string
  default = "v1.11.0"
}

variable "vpc_cni_version" {
  type    = string
  default = "v1.18.0"
}

variable "ebs_csi_version" {
  type    = string
  default = "v1.32.0"
}
