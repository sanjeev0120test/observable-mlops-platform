output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_oidc_provider_arn" {
  value = module.eks.oidc_provider_arn
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "private_subnet_ids" {
  value = module.vpc.private_subnets
}

output "mlflow_artifact_bucket" {
  description = "Use as MLFLOW_ARTIFACT_ROOT=s3://<bucket>/mlflow and DVC remote s3://<bucket>/dvc"
  value       = aws_s3_bucket.mlflow.bucket
}

output "mlflow_irsa_role_arn" {
  description = "Annotate the platform/mlflow ServiceAccount with eks.amazonaws.com/role-arn"
  value       = module.mlflow_irsa.iam_role_arn
}

output "kms_key_arn" {
  value = aws_kms_key.platform.arn
}

output "configure_kubectl" {
  value = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.region}"
}
