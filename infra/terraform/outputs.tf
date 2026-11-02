output "frontend_cloudfront_url" {
  description = "Public URL for the APIWeaver React Frontend (CloudFront Edge)"
  value       = var.enable_cloudfront ? "https://${aws_cloudfront_distribution.frontend[0].domain_name}" : "pending_aws_cloudfront_verification"
}

output "cloudfront_distribution_id" {
  description = "CloudFront Distribution ID for CI/CD cache invalidation"
  value       = var.enable_cloudfront ? aws_cloudfront_distribution.frontend[0].id : "pending_aws_cloudfront_verification"
}

output "frontend_s3_bucket" {
  description = "S3 bucket name for syncing compiled Frontend static build assets"
  value       = aws_s3_bucket.frontend.id
}

output "artifacts_s3_bucket" {
  description = "S3 bucket name for uploaded API specs and generated SDK artifact bundles"
  value       = aws_s3_bucket.artifacts.id
}

output "api_elastic_ip" {
  description = "Static Public IP of the API & Worker EC2 host (Point your api.domain.com DNS A record here)"
  value       = aws_eip.app_ip.public_ip
}

output "ec2_instance_id" {
  description = "EC2 Instance ID for AWS SSM commands and CI/CD automated deployments"
  value       = aws_instance.app_host.id
}

output "rds_endpoint" {
  description = "Private RDS PostgreSQL endpoint (accessible only from inside the VPC / EC2 host)"
  value       = aws_db_instance.postgres.endpoint
}

output "rds_address" {
  description = "Private RDS PostgreSQL hostname"
  value       = aws_db_instance.postgres.address
}

output "rds_master_secret_arn" {
  description = "AWS Secrets Manager ARN storing the auto-managed RDS master password"
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
}

output "ssm_connect_command" {
  description = "Command to open an interactive secure terminal on the EC2 host without SSH keys or open port 22"
  value       = "aws ssm start-session --target ${aws_instance.app_host.id}"
}
