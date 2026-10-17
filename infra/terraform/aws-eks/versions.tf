terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.80, < 7.0"
    }
  }

  # Remote state: uncomment and set the bucket once bootstrapped.
  # backend "s3" {
  #   bucket         = "observable-mlops-tfstate"
  #   key            = "aws-eks/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "observable-mlops-tflock"
  #   encrypt        = true
  # }
}
