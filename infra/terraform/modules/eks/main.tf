terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.20"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.10"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  cluster_name = var.cluster_name
}

data "aws_iam_policy_document" "cluster_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name = "${local.cluster_name}-cluster-role"

  assume_role_policy = data.aws_iam_policy_document.cluster_assume_role.json

  tags = {
    Name        = "${local.cluster_name}-cluster-role"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "cluster_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role_policy_attachment" "service_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSServicePolicy"
}

resource "aws_iam_role_policy_attachment" "cloudwatch_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

data "aws_iam_policy_document" "node_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node_general" {
  name = "${local.cluster_name}-node-general-role"

  assume_role_policy = data.aws_iam_policy_document.node_assume_role.json

  tags = {
    Name        = "${local.cluster_name}-node-general-role"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_iam_role" "node_agents" {
  name = "${local.cluster_name}-node-agents-role"

  assume_role_policy = data.aws_iam_policy_document.node_assume_role.json

  tags = {
    Name        = "${local.cluster_name}-node-agents-role"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "node_worker_policy_general" {
  role       = aws_iam_role.node_general.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "node_cni_policy_general" {
  role       = aws_iam_role.node_general.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Plugin_Policy"
}

resource "aws_iam_role_policy_attachment" "node_ecr_policy_general" {
  role       = aws_iam_role.node_general.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role_policy_attachment" "node_worker_policy_agents" {
  role       = aws_iam_role.node_agents.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "node_cni_policy_agents" {
  role       = aws_iam_role.node_agents.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Plugin_Policy"
}

resource "aws_iam_role_policy_attachment" "node_ecr_policy_agents" {
  role       = aws_iam_role.node_agents.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_instance_profile" "node_general" {
  name = "${local.cluster_name}-node-general-profile"
  role = aws_iam_role.node_general.name
}

resource "aws_iam_instance_profile" "node_agents" {
  name = "${local.cluster_name}-node-agents-profile"
  role = aws_iam_role.node_agents.name
}

# EKS Cluster Security Group
resource "aws_security_group" "cluster" {
  name_prefix = "${local.cluster_name}-cluster-sg"
  vpc_id      = var.vpc_id

  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.cluster_name}-cluster-sg"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

# EKS Cluster
resource "aws_eks_cluster" "main" {
  name     = local.cluster_name
  role_arn = aws_iam_role.cluster.arn
  version  = var.cluster_version

  vpc_config {
    subnet_ids              = var.private_subnets
    security_group_ids      = [aws_security_group.cluster.id]
    endpoint_private_access = true
    endpoint_public_access  = true
  }

  enabled_cluster_log_types = ["api", "audit", "app", "controllerManager"]

  tags = {
    Name        = local.cluster_name
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

# OIDC Identity Provider for IRSA
data "tls_certificate" "cluster" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "cluster" {
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.cluster.certificates[0].sha1_fingerprint]
}

# IRSA for S3 access
data "aws_iam_policy_document" "s3_access" {
  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket"
    ]
    resources = [
      var.s3_buckets.uploads,
      "${var.s3_buckets.uploads}/*",
      var.s3_buckets.artifacts,
      "${var.s3_buckets.artifacts}/*",
      var.s3_buckets.backups,
      "${var.s3_buckets.backups}/*"
    ]
  }
}

resource "aws_iam_policy" "s3_access" {
  name        = "${local.cluster_name}-s3-access"
  description = "IRSA policy for S3 access from EKS pods"
  policy      = data.aws_iam_policy_document.s3_access.json

  tags = {
    Name        = "${local.cluster_name}-s3-access"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

module "iam_assumable_role_admin" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "${local.cluster_name}-s3-sa"
  oidc_providers = {
    main = {
      provider_arn               = aws_iam_openid_connect_provider.cluster.arn
      namespace_service_accounts = ["default:apiweaver-sa"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "s3_access_attach" {
  role       = module.iam_assumable_role_admin.iam_role_name
  policy_arn = aws_iam_policy.s3_access.arn
}

# IRSA for ECR access
resource "aws_iam_policy" "ecr_access" {
  name        = "${local.cluster_name}-ecr-access"
  description = "IRSA policy for ECR access from EKS pods"
  policy      = data.aws_iam_policy_document.ecr_access.json

  tags = {
    Name        = "${local.cluster_name}-ecr-access"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

data "aws_iam_policy_document" "ecr_access" {
  statement {
    actions = [
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:GetImage",
      "ecr:GetAuthorizationToken"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy_attachment" "ecr_access_attach" {
  role       = module.iam_assumable_role_admin.iam_role_name
  policy_arn = aws_iam_policy.ecr_access.arn
}

# IRSA for EBS access
data "aws_iam_policy_document" "ebs_access" {
  statement {
    actions = [
      "ec2:CreateVolume",
      "ec2:AttachVolume",
      "ec2:DetachVolume",
      "ec2:DeleteVolume",
      "ec2:DescribeVolumes"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "ebs_access" {
  name        = "${local.cluster_name}-ebs-access"
  description = "IRSA policy for EBS access from EKS pods"
  policy      = data.aws_iam_policy_document.ebs_access.json

  tags = {
    Name        = "${local.cluster_name}-ebs-access"
    Project     = "APIWeaver"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "ebs_access_attach" {
  role       = module.iam_assumable_role_admin.iam_role_name
  policy_arn = aws_iam_policy.ebs_access.arn
}

# EKS Managed Node Group: General
resource "aws_eks_node_group" "general" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "general"
  node_role_arn   = aws_iam_role.node_general.arn
  instance_types  = ["m6i.xlarge"]
  subnet_ids      = var.private_subnets

  scaling_config {
    desired_size = 4
    max_size     = 10
    min_size     = 3
  }

  update_config {
    max_unavailable_percentage = 25
  }

  labels = {
    workload = "general"
  }

  tags = {
    Name        = "${local.cluster_name}-node-general"
    Project     = "APIWeaver"
    Environment = var.environment
  }

  depends_on = [
    aws_iam_role_policy_attachment.node_worker_policy_general,
    aws_iam_role_policy_attachment.node_cni_policy_general,
    aws_iam_role_policy_attachment.node_ecr_policy_general,
  ]
}

# EKS Managed Node Group: Agents
resource "aws_eks_node_group" "agents" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "agents"
  node_role_arn   = aws_iam_role.node_agents.arn
  instance_types  = ["c6i.2xlarge"]
  subnet_ids      = var.private_subnets

  taint {
    key    = "workload"
    value  = "agents"
    effect = "NO_SCHEDULE"
  }

  scaling_config {
    desired_size = 4
    max_size     = 20
    min_size     = 2
  }

  update_config {
    max_unavailable_percentage = 25
  }

  labels = {
    workload = "agents"
  }

  tags = {
    Name        = "${local.cluster_name}-node-agents"
    Project     = "APIWeaver"
    Environment = var.environment
  }

  depends_on = [
    aws_iam_role_policy_attachment.node_worker_policy_agents,
    aws_iam_role_policy_attachment.node_cni_policy_agents,
    aws_iam_role_policy_attachment.node_ecr_policy_agents,
  ]
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = "kube-proxy"
  addon_version = var.kube_proxy_version
}

resource "aws_eks_addon" "coredns" {
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = "coredns"
  addon_version = var.coredns_version
}

resource "aws_eks_addon" "vpc_cni" {
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = "vpc-cni"
  addon_version = var.vpc_cni_version
}

resource "aws_eks_addon" "ebs_csi" {
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = "aws-ebs-csi-driver"
  addon_version = var.ebs_csi_version

  service_account_role_arn = aws_iam_role.ebs_csi.arn
}

resource "aws_iam_role" "ebs_csi" {
  name = "${local.cluster_name}-ebs-csi-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "pods.eks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ebs_csi_attach" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}
