resource "aws_db_subnet_group" "rds" {
  name       = "${var.app_name}-${var.environment}-rds-subnet-group"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = {
    Name = "${var.app_name}-${var.environment}-rds-subnet-group"
  }
}

resource "aws_db_parameter_group" "postgres16" {
  name   = "${var.app_name}-${var.environment}-postgres16"
  family = "postgres16"

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  tags = {
    Name = "${var.app_name}-${var.environment}-postgres16"
  }
}

# Amazon RDS PostgreSQL 16
# Strictly configured for Cost Optimization (Free Tier Eligible) & Security:
# - Single-AZ (multi_az = false)
# - Isolated in private DB subnets (publicly_accessible = false)
# - Fixed 20 GB gp3 storage (max_allocated_storage = 20 prevents autoscaling bills)
# - Automated daily backups (backup_retention_period = 7)
# - Master password auto-managed in AWS Secrets Manager
resource "aws_db_instance" "postgres" {
  identifier     = "${var.app_name}-${var.environment}-db"
  engine         = "postgres"
  engine_version = "16.3"
  instance_class = var.rds_instance_class

  allocated_storage     = var.rds_allocated_storage
  max_allocated_storage = var.rds_allocated_storage # Capped to avoid exceeding Free Tier
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name                     = var.db_name
  username                    = var.db_username
  manage_master_user_password = true

  multi_az            = false
  publicly_accessible = false

  db_subnet_group_name   = aws_db_subnet_group.rds.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.postgres16.name

  backup_retention_period    = 0
  maintenance_window         = "sun:04:30-sun:05:30"
  auto_minor_version_upgrade = true
  skip_final_snapshot        = true # Set false if retaining final state on teardown

  tags = {
    Name = "${var.app_name}-${var.environment}-db"
  }
}
