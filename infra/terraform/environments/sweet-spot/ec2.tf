# Lookup the official Canonical Ubuntu 24.04 LTS ARM64 AMI for Graviton
data "aws_ami" "ubuntu_arm64" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }
}

# The Single EC2 Graviton Host (t4g.small - 2 vCPU, 2 GB RAM)
# Runs Docker Compose (Nginx, FastAPI, Celery, Redis, and Docker Socket Proxy)
resource "aws_instance" "app_host" {
  ami                    = data.aws_ami.ubuntu_arm64.id
  instance_type          = var.ec2_instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.ec2.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name

  root_block_device {
    volume_size           = var.ec2_volume_size
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true

    tags = {
      Name = "${var.app_name}-${var.environment}-root-volume"
    }
  }

  user_data = file("${path.module}/user_data.sh")

  tags = {
    Name = "${var.app_name}-${var.environment}-host"
  }

  lifecycle {
    ignore_changes = [ami]
  }
}

# Static Elastic IP attached to the EC2 Host ($0.00 within Free Tier 750h allowance)
resource "aws_eip" "app_ip" {
  domain = "vpc"

  tags = {
    Name = "${var.app_name}-${var.environment}-eip"
  }
}

resource "aws_eip_association" "app_ip_assoc" {
  instance_id   = aws_instance.app_host.id
  allocation_id = aws_eip.app_ip.id
}
