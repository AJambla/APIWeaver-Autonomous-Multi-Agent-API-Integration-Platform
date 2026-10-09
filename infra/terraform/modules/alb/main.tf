terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  name_prefix = "${var.environment}-apiweaver"
}

resource "aws_lb" "main" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_security_group]
  subnets            = var.public_subnets

  enable_deletion_protection = var.environment == "production" ? true : false

  tags = {
    Name        = "${local.name_prefix}-alb"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name_prefix}-api-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/healthz"
    healthy_threshold   = 2
    unhealthy_threshold = 10
    timeout             = 5
    interval            = 10
    matcher             = "200-399"
  }

  tags = {
    Name        = "${local.name_prefix}-api-tg"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_lb_target_group" "web" {
  name        = "${local.name_prefix}-web-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/healthz"
    healthy_threshold   = 2
    unhealthy_threshold = 10
    timeout             = 5
    interval            = 10
    matcher             = "200-399"
  }

  tags = {
    Name        = "${local.name_prefix}-web-tg"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = 443
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.certificate_arn

  # M11d: a listener created outside the console (Terraform uses the API) falls back to
  # `ELBSecurityPolicy-2016-08`, which still negotiates TLS 1.0 and TLS 1.1. The `-Res-`
  # policy drops both and keeps only AEAD suites. It cannot be a TLS 1.3-only policy: the
  # CloudFront origins (`modules/cloudfront/main.tf`, `origin_ssl_protocols = ["TLSv1.2"]`)
  # negotiate TLS 1.2 to this ALB, and this policy still offers all four of the AEAD suites
  # CloudFront brings to an origin handshake (ECDHE-{ECDSA,RSA}-{AES128,AES256}-GCM).
  ssl_policy = "ELBSecurityPolicy-TLS13-1-2-Res-2021-06"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }

}

# One rule per API path pattern: a listener has no inline `rule` block, so as written the
# API was never routed and every request reached the web target group.
resource "aws_lb_listener_rule" "api" {
  for_each = { for index, pattern in var.api_path_patterns : tostring(index) => pattern }

  listener_arn = aws_lb_listener.https.arn
  priority     = tonumber(each.key) + 1

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = [each.value]
    }
  }
}
