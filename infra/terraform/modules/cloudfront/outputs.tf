output "distribution_domain_name" {
  description = "CloudFront distribution domain name"
  value       = aws_cloudfront_distribution.main.domain_name
}

output "distribution_id" {
  description = "CloudFront distribution ID"
  value       = aws_cloudfront_distribution.main.id
}

output "distribution_zone_id" {
  description = "CloudFront distribution zone ID"
  value       = aws_cloudfront_distribution.main.hosted_zone_id
}
