variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (production, staging)"
  type        = string
}

variable "domain" {
  description = "Base domain for APIWeaver"
  type        = string
}

# Deliberately required: `aws_eks_cluster` documents that public access with no CIDR list means
# 0.0.0.0/0, so the way to make "forgot to set it" safe is to refuse to plan at all. Supply your
# admin networks (host routes, e.g. "203.0.113.7/32") in a tfvars file. To drop the public
# endpoint entirely instead, set endpoint_public_access = false in modules/eks/main.tf - that
# requires in-VPC access (bastion or VPN) for kubectl.
variable "eks_public_access_cidrs" {
  description = "CIDR blocks allowed to reach the public EKS API server endpoint"
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.eks_public_access_cidrs) > 0
    error_message = "eks_public_access_cidrs must list at least one admin CIDR; leaving it empty would fall back to 0.0.0.0/0."
  }

  validation {
    condition     = alltrue([for c in var.eks_public_access_cidrs : c != "0.0.0.0/0" && c != "::/0"])
    error_message = "eks_public_access_cidrs may not contain 0.0.0.0/0 or ::/0."
  }
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs for EKS nodes"
  type        = list(string)
  default     = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
}

variable "data_plane_cidrs" {
  description = "Data plane subnet CIDRs for RDS/ElastiCache/Qdrant"
  type        = list(string)
  default     = ["10.0.21.0/24", "10.0.22.0/24", "10.0.23.0/24"]
}

variable "availability_zones" {
  description = "Availability zones"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "create_waf" {
  description = "Create AWS WAF for CloudFront"
  type        = bool
  default     = false
}

variable "certificate_arn" {
  description = "ARN of the SSL certificate for ALB and CloudFront"
  type        = string
}

variable "cloudfront_certificate_arn" {
  description = "ACM certificate for the CloudFront distribution. CloudFront only accepts certificates issued in us-east-1."
  type        = string
}

variable "elasticache_auth_token" {
  description = "Redis AUTH token (16-128 printable characters). Supply it from a secret store, e.g. TF_VAR_elasticache_auth_token; it is stored in state."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.elasticache_auth_token) >= 16 && length(var.elasticache_auth_token) <= 128
    error_message = "elasticache_auth_token must be 16-128 characters."
  }
}
