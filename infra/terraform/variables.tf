variable "aws_region" {
  description = "AWS region for resources (Asia Pacific Mumbai: ap-south-1)"
  type        = string
  default     = "ap-south-1"
}

variable "environment" {
  description = "Deployment environment name (e.g., production, staging)"
  type        = string
  default     = "production"
}

variable "app_name" {
  description = "Application name prefix"
  type        = string
  default     = "apiweaver"
}

variable "ec2_instance_type" {
  description = "EC2 instance size for Docker Compose host (Graviton ARM64 recommended: t4g.small)"
  type        = string
  default     = "t4g.small"
}

variable "ec2_volume_size" {
  description = "Root EBS gp3 volume size in GB"
  type        = number
  default     = 25
}

variable "rds_instance_class" {
  description = "RDS PostgreSQL instance type (db.t4g.micro is Free Tier eligible)"
  type        = string
  default     = "db.t4g.micro"
}

variable "rds_allocated_storage" {
  description = "RDS allocated storage in GB (Free tier limit is 20 GB)"
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Initial PostgreSQL database name"
  type        = string
  default     = "apiweaver"
}

variable "db_username" {
  description = "PostgreSQL master username"
  type        = string
  default     = "apiweaver_admin"
}

variable "domain_name" {
  description = "Optional custom domain name (e.g. yourdomain.com). If empty, default CloudFront URL is used."
  type        = string
  default     = ""
}

variable "acm_certificate_arn" {
  description = "Optional ACM certificate ARN in us-east-1 for custom domain on CloudFront"
  type        = string
  default     = ""
}

variable "enable_cloudfront" {
  description = "Enable CloudFront CDN distribution for frontend (set false if AWS account is pending CloudFront verification)"
  type        = bool
  default     = false
}
