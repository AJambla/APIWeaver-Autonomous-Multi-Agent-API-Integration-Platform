terraform {
  backend "s3" {}
}

locals {
  state_bucket = "apiweaver-terraform-state-${var.environment}"
  lock_table   = "apiweaver-terraform-locks"
}

resource "aws_s3_bucket" "terraform_state" {
  count  = terraform.workspace != "default" ? 1 : 0
  bucket = local.state_bucket

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name        = local.state_bucket
    Project     = "APIWeaver"
    Environment = var.environment
    Purpose     = "Terraform Remote State"
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  count  = terraform.workspace != "default" ? 1 : 0
  bucket = aws_s3_bucket.terraform_state[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  count  = terraform.workspace != "default" ? 1 : 0
  bucket = aws_s3_bucket.terraform_state[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = module.kms.key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  count  = terraform.workspace != "default" ? 1 : 0
  bucket = aws_s3_bucket.terraform_state[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "terraform_locks" {
  count        = terraform.workspace != "default" ? 1 : 0
  name         = local.lock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Name        = local.lock_table
    Project     = "APIWeaver"
    Environment = var.environment
    Purpose     = "Terraform State Locking"
  }
}
