output "endpoint" {
  description = "RDS endpoint"
  value       = aws_db_instance.main.endpoint
}

output "port" {
  description = "RDS port"
  value       = aws_db_instance.main.port
}

output "db_name" {
  description = "Database name"
  value       = aws_db_instance.main.db_name
}

output "master_user_secret_arn" {
  description = "Secrets Manager secret holding the generated master credentials"
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}
