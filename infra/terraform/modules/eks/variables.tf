variable "region" {
  description = "AWS region"
  type        = string
}

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
