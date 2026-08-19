variable "region" {
  description = "AWS region"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "public_subnets" {
  description = "Public subnet IDs"
  type        = list(string)
}

variable "alb_security_group" {
  description = "Security group for ALB"
  type        = string
}

variable "api_security_group" {
  description = "Security group for API targets"
  type        = string
}

variable "web_security_group" {
  description = "Security group for web targets"
  type        = string
}

variable "domain" {
  description = "Base domain"
  type        = string
}

variable "certificate_arn" {
  description = "ARN of the SSL certificate"
  type        = string
}

variable "api_path_patterns" {
  description = "Path patterns to route to API target group"
  type        = list(string)
  default     = ["/api/*", "/ws/*"]
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}
