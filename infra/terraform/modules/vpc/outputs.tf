output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "public_subnets" {
  description = "Public subnet IDs"
  value       = aws_subnet.public[*].id
}

output "private_subnets" {
  description = "Private subnet IDs for EKS"
  value       = aws_subnet.private[*].id
}

output "data_plane_subnets" {
  description = "Data plane subnet IDs"
  value       = aws_subnet.data_plane[*].id
}

output "db_subnet_group_name" {
  description = "DB subnet group name for RDS"
  value       = aws_db_subnet_group.main.name
}

output "alb_security_group_id" {
  description = "Security group ID for ALB"
  value       = aws_security_group.alb.id
}

output "api_security_group_id" {
  description = "Security group ID for API/Web targets"
  value       = aws_security_group.api_web.id
}

output "web_security_group_id" {
  description = "Security group ID for web targets"
  value       = aws_security_group.api_web.id
}

output "api_data_security_group_id" {
  description = "Security group ID for API data layer access"
  value       = aws_security_group.api_data.id
}

output "agent_worker_security_group_id" {
  description = "Security group ID for agent worker"
  value       = aws_security_group.agent_worker.id
}
