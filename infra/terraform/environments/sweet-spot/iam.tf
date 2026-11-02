data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2_role" {
  name_prefix        = "${var.app_name}-${var.environment}-ec2-role-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json

  tags = {
    Name = "${var.app_name}-${var.environment}-ec2-role"
  }
}

# Attach AWS SSM Managed Instance Core: Enables browser-based terminal & SSM Run Command without SSH port 22
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# S3 Access Policy for APIWeaver storage service (Uploads and Artifacts)
data "aws_iam_policy_document" "s3_access" {
  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket"
    ]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*"
    ]
  }
}

resource "aws_iam_policy" "s3_access" {
  name_prefix = "${var.app_name}-${var.environment}-s3-policy-"
  description = "Allows APIWeaver containers to manage spec uploads and generated SDK artifacts in S3"
  policy      = data.aws_iam_policy_document.s3_access.json
}

resource "aws_iam_role_policy_attachment" "s3_access" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.s3_access.arn
}

# SSM Parameter Store Read Policy for application secrets
data "aws_iam_policy_document" "ssm_parameters" {
  statement {
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath"
    ]
    resources = [
      "arn:aws:ssm:${var.aws_region}:*:parameter/${var.app_name}/${var.environment}/*"
    ]
  }
}

resource "aws_iam_policy" "ssm_parameters" {
  name_prefix = "${var.app_name}-${var.environment}-ssm-param-policy-"
  description = "Allows EC2 host to read encrypted application parameters from SSM Parameter Store"
  policy      = data.aws_iam_policy_document.ssm_parameters.json
}

resource "aws_iam_role_policy_attachment" "ssm_parameters" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.ssm_parameters.arn
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name_prefix = "${var.app_name}-${var.environment}-ec2-profile-"
  role        = aws_iam_role.ec2_role.name
}
