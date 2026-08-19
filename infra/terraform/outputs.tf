output "alb_dns_name" {
  description = "DNS name of the ALB"
  value       = module.alb.alb_dns_name
}

output "alb_zone_id" {
  description = "Zone ID of the ALB"
  value       = module.alb.alb_zone_id
}

output "cloudfront_domain" {
  description = "CloudFront distribution domain name"
  value       = module.cloudfront.distribution_domain_name
}

output "cloudfront_id" {
  description = "CloudFront distribution ID"
  value       = module.cloudfront.distribution_id
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint"
  value       = module.rds.endpoint
}

output "rds_port" {
  description = "RDS PostgreSQL port"
  value       = module.rds.port
}

output "rds_db_name" {
  description = "RDS PostgreSQL database name"
  value       = module.rds.db_name
}

output "redis_endpoint" {
  description = "Redis primary endpoint"
  value       = module.elasticache.primary_endpoint
}

output "redis_port" {
  description = "Redis port"
  value       = module.elasticache.port
}

output "redis_auth_token" {
  description = "Redis auth token (sensitive)"
  value       = module.elasticache.auth_token
  sensitive   = true
}

output "eks_cluster_endpoint" {
  description = "EKS cluster endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "eks_cluster_ca" {
  description = "EKS cluster certificate authority data"
  value       = module.eks.cluster_certificate_authority_data
}

output "kms_key_arn" {
  description = "KMS key ARN"
  value       = module.kms.key_arn
}

output "route53_zone_id" {
  description = "Route53 hosted zone ID"
  value       = module.route53.zone_id
}

output "s3_uploads_bucket" {
  description = "S3 bucket for uploads"
  value       = module.s3.uploads_bucket
}

output "s3_artifacts_bucket" {
  description = "S3 bucket for artifacts"
  value       = module.s3.artifacts_bucket
}

output "s3_backups_bucket" {
  description = "S3 bucket for backups"
  value       = module.s3.backups_bucket
}

output "terraform_state_bucket" {
  description = "S3 bucket for Terraform remote state"
  value       = terraform.workspace != "default" ? aws_s3_bucket.terraform_state[0].id : null
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}
