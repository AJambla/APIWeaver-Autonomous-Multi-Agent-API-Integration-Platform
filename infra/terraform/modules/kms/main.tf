terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  name_prefix = "${var.environment}-apiweaver"
}

resource "aws_kms_key" "main" {
  description             = var.description
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Enable IAM User Permissions"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      }
    ]
  })

  tags = {
    Name        = "${local.name_prefix}-kms-key"
    Project     = "APIWeaver"
    Environment = var.environment
    Purpose     = "RDS, S3, EBS encryption"
  }
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name_prefix}-kms-key"
  target_key_id = aws_kms_key.main.key_id
}

data "aws_caller_identity" "current" {}
