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

resource "aws_db_subnet_group" "rds" {
  name       = "${local.name_prefix}-rds-subnet-group"
  subnet_ids = var.data_plane_subnets

  tags = {
    Name        = "${local.name_prefix}-rds-subnet-group"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_security_group" "rds" {
  name_prefix = "${local.name_prefix}-rds-sg"
  description = "Security group for RDS PostgreSQL"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = var.allowed_security_groups
  }

  tags = {
    Name        = "${local.name_prefix}-rds-sg"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_db_parameter_group" "postgres16" {
  name   = "${local.name_prefix}-postgres16"
  family = "postgres16"

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  parameter {
    name  = "log_statement"
    value = "all"
  }

  tags = {
    Name        = "${local.name_prefix}-postgres16"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_db_instance" "main" {
  identifier     = "${local.name_prefix}-postgres"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = 100
  max_allocated_storage = 1000
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = var.kms_key_id

  db_subnet_group_name   = aws_db_subnet_group.rds.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  db_name  = var.db_name
  username = var.master_username
  password = var.master_password
  port     = 5432

  multi_az             = true
  publicly_accessible  = false
  skip_final_snapshot  = var.environment == "production" ? false : true
  final_snapshot_identifier = "${local.name_prefix}-postgres-final-snapshot"

  backup_retention_period = var.backup_retention_period
  backup_window           = "07:00-09:00"
  maintenance_window      = "sun:10:00-sun:12:00"
  auto_minor_version_upgrade = true

  enabled_cloudwatch_logs_exports = ["postgresql"]

  tags = {
    Name        = "${local.name_prefix}-postgres"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "null_resource" "audit_logs_grants" {
  depends_on = [aws_db_instance.main]

  triggers = {
    db_endpoint    = aws_db_instance.main.endpoint
    db_name        = var.db_name
    master_user    = var.master_username
    db_app_role    = var.db_app_role
  }

  provisioner "local-exec" {
    command = <<-EOT
      PGPASSWORD="${var.master_password}" psql \
        -h "${split(":", aws_db_instance.main.endpoint)[0]}" \
        -p "${aws_db_instance.main.port}" \
        -U "${var.master_username}" \
        -d "${var.db_name}" \
        -c "DO $$ BEGIN GRANT INSERT, SELECT ON audit_logs TO ${var.db_app_role}; REVOKE UPDATE, DELETE ON audit_logs FROM ${var.db_app_role}; EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'audit_logs grants already applied or table does not exist'; END $$;"
    EOT
    interpreter = ["bash", "-c"]
  }
}
