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
  common_tags = {
    Project     = "APIWeaver"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

module "vpc" {
  source = "./modules/vpc"

  environment = var.environment
  cidr_block  = var.vpc_cidr

  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  data_plane_cidrs     = var.data_plane_cidrs

  availability_zones = var.availability_zones

  tags = local.common_tags
}

module "kms" {
  source = "./modules/kms"

  environment = var.environment
  description = "APIWeaver ${var.environment} KMS key for RDS, S3, and EBS encryption"

  tags = local.common_tags
}

module "rds" {
  source = "./modules/rds"

  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  data_plane_subnets = module.vpc.data_plane_subnets
  kms_key_id         = module.kms.key_arn

  allowed_security_groups = [module.vpc.api_security_group_id, module.eks.cluster_security_group_id]

  engine_version = "16.3"
  instance_class = "db.r6g.xlarge"

  tags = local.common_tags
}

module "elasticache" {
  source = "./modules/elasticache"

  environment       = var.environment
  vpc_id            = module.vpc.vpc_id
  data_plane_subnets = module.vpc.data_plane_subnets
  kms_key_id        = module.kms.key_arn

  allowed_security_groups = [module.eks.cluster_security_group_id]

  tags = local.common_tags
}

module "s3" {
  source = "./modules/s3"

  environment = var.environment
  kms_key_id  = module.kms.key_arn

  tags = local.common_tags
}

module "alb" {
  source = "./modules/alb"

  environment          = var.environment
  vpc_id               = module.vpc.vpc_id
  public_subnets       = module.vpc.public_subnets
  alb_security_group   = module.vpc.alb_security_group_id
  api_security_group   = module.vpc.api_security_group_id
  web_security_group   = module.vpc.web_security_group_id

  domain          = var.domain
  certificate_arn = var.certificate_arn

  tags = local.common_tags
}

module "cloudfront" {
  source = "./modules/cloudfront"

  environment      = var.environment
  alb_dns_name     = module.alb.alb_dns_name
  alb_zone_id      = module.alb.alb_zone_id
  web_origin_id    = "ALB-web"
  api_origin_id    = "ALB-api"
  domain           = var.domain
  create_waf       = var.create_waf

  tags = local.common_tags
}

module "eks" {
  source = "./modules/eks"

  environment = var.environment
  cluster_name = "apiweaver-${var.environment}"

  vpc_id          = module.vpc.vpc_id
  private_subnets = module.vpc.private_subnets

  s3_buckets = {
    uploads    = module.s3.uploads_bucket
    artifacts  = module.s3.artifacts_bucket
    backups    = module.s3.backups_bucket
  }

  tags = local.common_tags
}

module "route53" {
  source = "./modules/route53"

  environment        = var.environment
  domain             = var.domain
  cloudfront_domain  = module.cloudfront.distribution_domain_name
  cloudfront_zone_id = module.cloudfront.distribution_zone_id
  alb_dns_name       = module.alb.alb_dns_name
  alb_zone_id        = module.alb.alb_zone_id

  tags = local.common_tags
}
