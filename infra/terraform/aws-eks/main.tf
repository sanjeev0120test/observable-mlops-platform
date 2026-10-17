# Production EKS footprint for the observable-mlops-platform.
#
#   VPC (3 AZ, private nodes, single NAT in dev / per-AZ NAT in production)
#   EKS with IRSA + Pod Identity, encrypted secrets, control-plane logs to CloudWatch
#   Node groups:
#     platform  — on-demand, always-on (services, OPA, MLflow, Airflow, Prometheus)
#     inference — spot, scale-to-zero capable (KServe predictors, batch scoring)
#   S3 bucket for MLflow artifacts + DVC remote, versioned, SSE-KMS, public access blocked
#   IRSA roles for MLflow (artifact bucket) and the self-healing service (scoped K8s remediation)
#
# Apply:  terraform init && terraform apply -var environment=production
# Then:   aws eks update-kubeconfig --name observable-mlops --region us-east-1
#         kubectl apply -k ../../kubernetes/base/self-healing
#         kubectl apply -k ../../kubernetes/base/model-trust

provider "aws" {
  region = var.region

  default_tags {
    tags = merge(
      {
        Project     = "observable-mlops-platform"
        Environment = var.environment
        ManagedBy   = "terraform"
        Repository  = "github.com/sanjeev0120test/observable-mlops-platform"
      },
      var.tags,
    )
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  azs           = slice(data.aws_availability_zones.available.names, 0, 3)
  is_production = var.environment == "production"
  bucket_name = var.mlflow_artifact_bucket_name != "" ? var.mlflow_artifact_bucket_name : lower(
    "${var.cluster_name}-mlflow-${data.aws_caller_identity.current.account_id}"
  )
}

# ──────────────────────────────── Networking ────────────────────────────────
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.17"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr
  azs  = local.azs

  private_subnets = [for k, v in local.azs : cidrsubnet(var.vpc_cidr, 4, k)]
  public_subnets  = [for k, v in local.azs : cidrsubnet(var.vpc_cidr, 8, k + 48)]

  enable_nat_gateway     = true
  single_nat_gateway     = !local.is_production
  one_nat_gateway_per_az = local.is_production
  enable_dns_hostnames   = true
  enable_dns_support     = true

  # VPC flow logs → CloudWatch (Falco/UC7 and incident forensics)
  enable_flow_log                      = true
  create_flow_log_cloudwatch_iam_role  = true
  create_flow_log_cloudwatch_log_group = true
  flow_log_max_aggregation_interval    = 60

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
    "karpenter.sh/discovery"          = var.cluster_name
  }
}

# ──────────────────────────────── KMS ───────────────────────────────────────
resource "aws_kms_key" "platform" {
  description             = "${var.cluster_name}: EKS secrets, MLflow artifacts, logs"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "platform" {
  name          = "alias/${var.cluster_name}"
  target_key_id = aws_kms_key.platform.key_id
}

# ──────────────────────────────── EKS ───────────────────────────────────────
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.private_subnets
  control_plane_subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access       = var.enable_public_endpoint
  cluster_endpoint_public_access_cidrs = var.endpoint_public_access_cidrs
  cluster_endpoint_private_access      = true

  enable_cluster_creator_admin_permissions = true
  authentication_mode                      = "API_AND_CONFIG_MAP"

  cluster_encryption_config = {
    provider_key_arn = aws_kms_key.platform.arn
    resources        = ["secrets"]
  }

  cluster_enabled_log_types              = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  cloudwatch_log_group_retention_in_days = local.is_production ? 365 : 30
  cloudwatch_log_group_kms_key_id        = aws_kms_key.platform.arn

  enable_irsa = true

  cluster_addons = {
    coredns                = { most_recent = true }
    kube-proxy             = { most_recent = true }
    vpc-cni                = { most_recent = true, before_compute = true }
    eks-pod-identity-agent = { most_recent = true }
    aws-ebs-csi-driver = {
      most_recent              = true
      service_account_role_arn = module.ebs_csi_irsa.iam_role_arn
    }
  }

  eks_managed_node_group_defaults = {
    ami_type       = "AL2023_x86_64_STANDARD"
    disk_size      = 50
    capacity_type  = "ON_DEMAND"
    instance_types = var.platform_node_instance_types

    metadata_options = {
      http_endpoint               = "enabled"
      http_tokens                 = "required" # IMDSv2 only
      http_put_response_hop_limit = 1
    }

    block_device_mappings = {
      xvda = {
        device_name = "/dev/xvda"
        ebs = {
          volume_size           = 50
          volume_type           = "gp3"
          encrypted             = true
          kms_key_id            = aws_kms_key.platform.arn
          delete_on_termination = true
        }
      }
    }
  }

  eks_managed_node_groups = {
    platform = {
      name           = "platform"
      min_size       = var.platform_node_min_size
      max_size       = var.platform_node_max_size
      desired_size   = var.platform_node_min_size
      instance_types = var.platform_node_instance_types
      labels = {
        "platform.observable-mlops/pool" = "platform"
      }
    }

    inference = {
      name           = "inference"
      min_size       = 0
      max_size       = var.inference_node_max_size
      desired_size   = 0
      capacity_type  = "SPOT"
      instance_types = var.inference_node_instance_types
      labels = {
        "platform.observable-mlops/pool" = "inference"
      }
      taints = {
        inference = {
          key    = "platform.observable-mlops/inference"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      }
    }
  }

  node_security_group_tags = {
    "karpenter.sh/discovery" = var.cluster_name
  }
}

# ──────────────────────────────── IRSA roles ────────────────────────────────
module "ebs_csi_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.52"

  role_name             = "${var.cluster_name}-ebs-csi"
  attach_ebs_csi_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }
}

# MLflow server: read/write only its artifact bucket.
data "aws_iam_policy_document" "mlflow_artifacts" {
  statement {
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.mlflow.arn]
  }
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.mlflow.arn}/*"]
  }
  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.platform.arn]
  }
}

resource "aws_iam_policy" "mlflow_artifacts" {
  name   = "${var.cluster_name}-mlflow-artifacts"
  policy = data.aws_iam_policy_document.mlflow_artifacts.json
}

module "mlflow_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.52"

  role_name = "${var.cluster_name}-mlflow"
  role_policy_arns = {
    artifacts = aws_iam_policy.mlflow_artifacts.arn
  }
  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["platform:mlflow"]
    }
  }
}

# ──────────────────────────────── S3: MLflow artifacts + DVC remote ─────────
resource "aws_s3_bucket" "mlflow" {
  bucket        = local.bucket_name
  force_destroy = !local.is_production
}

resource "aws_s3_bucket_versioning" "mlflow" {
  bucket = aws_s3_bucket.mlflow.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "mlflow" {
  bucket = aws_s3_bucket.mlflow.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.platform.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "mlflow" {
  bucket                  = aws_s3_bucket.mlflow.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "mlflow" {
  bucket = aws_s3_bucket.mlflow.id

  rule {
    id     = "expire-noncurrent-artifacts"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = local.is_production ? 365 : 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
