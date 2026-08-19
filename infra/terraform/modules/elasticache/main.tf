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

resource "aws_elasticache_subnet_group" "main" {
  name       = "${local.name_prefix}-redis-subnet-group"
  subnet_ids = var.data_plane_subnets

  tags = {
    Name        = "${local.name_prefix}-redis-subnet-group"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_security_group" "redis" {
  name_prefix = "${local.name_prefix}-redis-sg"
  description = "Security group for ElastiCache Redis"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = var.allowed_security_groups
  }

  tags = {
    Name        = "${local.name_prefix}-redis-sg"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id         = "${local.name_prefix}-redis"
  description                  = "APIWeaver Redis cluster"
  engine                       = "redis"
  engine_version               = "7.1"
  node_type                    = var.node_type
  port                         = 6379
  number_cache_clusters        = var.num_cache_nodes
  subnet_group_name            = aws_elasticache_subnet_group.main.name
  security_group_ids           = [aws_security_group.redis.id]
  at_rest_encryption_enabled   = true
  transit_encryption_enabled   = true
  auth_token                   = var.auth_token
  kms_key_id                   = var.kms_key_id

  automatic_failover_enabled = true
  multi_az_enabled           = true

  log_delivery_configuration {
    destination      = "cloudwatch"
    destination_type = "cloudwatch-logs"
    log_format       = "text"
    log_type         = "slow-log"
  }

  tags = {
    Name        = "${local.name_prefix}-redis"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}
