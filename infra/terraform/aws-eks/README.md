# AWS EKS footprint

Terraform for the production Kubernetes footprint of the platform.

| Resource | Purpose |
| --- | --- |
| VPC, 3 AZs, private node subnets, flow logs | network isolation; NAT per AZ in `production` |
| EKS (IRSA + Pod Identity, KMS-encrypted secrets, all control-plane logs) | cluster |
| `platform` node group (on-demand) | services, OPA, MLflow, Airflow, Prometheus |
| `inference` node group (spot, 0→N, tainted) | KServe predictors, batch scoring |
| S3 bucket (versioned, SSE-KMS, no public access, lifecycle) | MLflow artifacts + DVC remote |
| IRSA role `…-mlflow` | MLflow server access scoped to that bucket |
| KMS key with rotation | secrets, EBS volumes, logs, bucket |

```bash
cd infra/terraform/aws-eks
terraform init
terraform plan  -var environment=dev
terraform apply -var environment=dev
$(terraform output -raw configure_kubectl)

kubectl create namespace platform
kubectl apply -k ../../kubernetes/base/self-healing
kubectl apply -k ../../kubernetes/base/model-trust
```

`terraform fmt -check` and `terraform validate` run in CI (workflow 13). No `apply` runs in CI.
