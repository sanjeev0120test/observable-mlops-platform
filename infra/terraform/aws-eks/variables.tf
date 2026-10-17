variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "observable-mlops"
}

variable "cluster_version" {
  description = "Kubernetes version for the EKS control plane"
  type        = string
  default     = "1.33"
}

variable "environment" {
  description = "Environment tag (dev | staging | production)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "environment must be dev, staging or production."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the platform VPC"
  type        = string
  default     = "10.42.0.0/16"
}

variable "platform_node_instance_types" {
  description = "Instance types for the always-on platform node group (services, OPA, MLflow, Airflow)"
  type        = list(string)
  default     = ["m6i.large", "m5.large"]
}

variable "platform_node_min_size" {
  type    = number
  default = 2
}

variable "platform_node_max_size" {
  type    = number
  default = 6
}

variable "inference_node_instance_types" {
  description = "Instance types for the spot inference node group (KServe predictors)"
  type        = list(string)
  default     = ["c6i.xlarge", "c5.xlarge", "c6a.xlarge"]
}

variable "inference_node_max_size" {
  type    = number
  default = 10
}

variable "enable_public_endpoint" {
  description = "Expose the EKS API server publicly (restrict with endpoint_public_access_cidrs)"
  type        = bool
  default     = true
}

variable "endpoint_public_access_cidrs" {
  description = "CIDRs allowed to reach a public API endpoint"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "mlflow_artifact_bucket_name" {
  description = "S3 bucket for MLflow artifacts and DVC remote (globally unique). Empty = derive from cluster name + account id."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Extra tags applied to every resource"
  type        = map(string)
  default     = {}
}
