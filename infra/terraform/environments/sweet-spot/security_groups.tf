# EC2 Security Group: Inbound HTTP/HTTPS only.
# Port 22 (SSH) is closed: zero attack surface. Administration is via AWS SSM Session Manager.
resource "aws_security_group" "ec2" {
  name_prefix = "${var.app_name}-${var.environment}-ec2-sg-"
  description = "Security group for APIWeaver Docker host"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP for Let's Encrypt validation and HTTPS redirection"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS for production API traffic"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic for GHCR, LLM APIs, and Qdrant Cloud"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.app_name}-${var.environment}-ec2-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# RDS Security Group: Strictly isolated inside the private subnets.
# Accepts port 5432 ONLY from the EC2 instance's security group.
resource "aws_security_group" "rds" {
  name_prefix = "${var.app_name}-${var.environment}-rds-sg-"
  description = "Security group for APIWeaver RDS PostgreSQL"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from EC2 host only"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2.id]
  }

  tags = {
    Name = "${var.app_name}-${var.environment}-rds-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}
