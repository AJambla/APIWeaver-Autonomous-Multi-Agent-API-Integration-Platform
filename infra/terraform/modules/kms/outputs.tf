output "key_arn" {
  description = "KMS key ARN"
  value       = aws_kms_key.main.arn
}

output "key_id" {
  description = "KMS key ID"
  value       = aws_kms_key.main.key_id
}
