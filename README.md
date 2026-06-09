# Observable MLOps Platform

Enterprise-grade **AIOps + MLOps** reference platform — **23 use cases**, all fully built end-to-end with blocking CI eval gates. Zero local execution required — runs entirely via GitHub Actions.

## Architecture at a Glance

```
GitHub Actions (27 workflows, 00-26 + 90-91)
├── Docker Compose Stack A  — MLflow(DagsHub) + Feast + PostgreSQL + Redis + Airflow + n8n + Qdrant + Ollama
├── Docker Compose Stack B  — Prometheus + Alertmanager + Grafana + Loki + Tempo + OTEL + FluentBit
├── Kind Job A              — KServe + Knative (UC9, UC22 model serving)
├── Kind Job B              — Kubeflow Pipelines + Argo (UC9, UC14 ML DAGs)
└── Kind Job C              — Kyverno + KEDA + OPA (UC4, UC7, UC12)
```

**Persistence**: [DagsHub](https://dagshub.com) (MLflow tracking + DVC remote — free, one token)
**Reports**: GitHub Pages (HTML drift reports, eval scorecards)
**Portal**: GitHub Pages (default) | HuggingFace Spaces Gradio (opt-in with `HF_TOKEN`)

## 23 Use Cases

| # | Use Case | Key Tools | Workflow |
|---|---|---|---|
| UC1  | ML Model Drift Detection + Auto-Retraining | Evidently, NannyML, Alibi Detect, Airflow | `03-drift-detection` |
| UC2  | Log Anomaly Detection | PyTorch LSTM, Loki, FluentBit, Qdrant | `04-log-anomaly` |
| UC3  | Alert Correlation & Fatigue Reduction | sklearn DBSCAN, Prometheus, Alertmanager | `06-alert-correlation` |
| UC4  | Predictive Autoscaling | Prophet, KEDA, Prometheus | `07-predictive-scaling` |
| UC5  | Feature Store + Training-Serving Skew | Feast, Redis, Evidently, Great Expectations | `05-feature-skew` |
| UC6  | Agentic Self-Healing Runbooks | Falco, n8n, OPA, kubectl | `08-self-healing` |
| UC7  | Security Policy Enforcement | Trivy, Falco, Kyverno, OPA, SBOM | `13-security-policy` |
| UC8  | RAG Runbook Q&A Agent | Qdrant, sentence-transformers, TinyLlama, LangChain | `09-rag-runbook` |
| UC9  | Experiment Tracking + Registry + Canary Serving | MLflow, DVC, Kubeflow, KServe | `10-model-serving` |
| UC10 | Cloud Cost Anomaly + Attribution | IsolationForest, Prometheus, Pandas | `11-cost-optimizer` |
| UC11 | Distributed Tracing + RCA | OTEL, Tempo, Grafana, sklearn | `18-distributed-tracing` |
| UC12 | GitOps Compliance Drift | ArgoCD, Kyverno, OPA | `19-gitops-drift` |
| UC13 | Data Pipeline Quality Gates | Great Expectations, Airflow | `20-data-quality` |
| UC14 | Hyperparameter Optimization | Optuna, MLflow, Kubeflow | `21-hpo` |
| UC15 | DORA Metrics Dashboard | GHA events, Prometheus, Grafana | `14-dora-metrics` |
| UC16 | Intelligent Error Classification | sklearn, sentence-transformers | `22-error-classification` |
| UC17 | Model Explainability + Audit | SHAP, MLflow, OPA | `23-explainability` |
| UC18 | Predictive Rate Limiting | Redis, sklearn, KEDA | `24-rate-limiting` |
| UC19 | Feature Monitoring (WhyLogs) | WhyLogs, WhyLabs (opt-in) | `25-feature-monitoring` |
| UC20 | Backstage Service Catalog | catalog-info.yaml, entity lint | `26-catalog-validate` |
| UC21 | SLO / Error Budget Monitoring | Prometheus recording rules, Grafana | `15-slo-monitoring` |
| UC22 | Model A/B Testing | KServe, scipy stats | `10-model-serving` |
| UC23 | Automated Post-Mortem Generation | n8n, Qdrant, TinyLlama, GitHub Issues | `09-rag-runbook` |

## Quick Start

### Prerequisites
- GitHub account (public repo for unlimited Actions minutes)
- [DagsHub](https://dagshub.com) free account → create a repo → get token

### 1. Fork and configure secrets

```bash
# In your GitHub repo → Settings → Secrets → Actions
# Add: DAGSHUB_TOKEN   (required — everything else runs without it too)
# Add: HF_TOKEN        (optional — activates HuggingFace Hub artifacts + Spaces portal)
# Add: WHYLABS_API_KEY (optional — activates WhyLabs cloud dashboard)
# Add: WHYLABS_ORG_ID  (optional — paired with WHYLABS_API_KEY)
```

### 2. Run Phase 0 validate workflow

Push to `main` — GitHub Actions will run `00-pr-validate` automatically and report all eval gates.

### 3. Watch the portal

After `91-publish-portal` completes, visit `https://<your-org>.github.io/observable-mlops-platform/`

## Repository Structure

```
.github/workflows/       27 workflow files (00-26 + 90-91)
infra/
  docker-compose/        Stack A (ML/data) + Stack B (observability) + services
  kind/                  Kind cluster configs (Job A/B/C)
  helm/                  Helm values per component
  terraform/             Reference IaC (aws-eks, gcp-gke)
  crossplane/            XRD reference manifests
services/                One folder per UC service (UC2/6/7/8/10)
mlops/
  feature-store/         Feast feature definitions + materialize script
  pipelines/             Airflow DAGs + Kubeflow pipelines
  experiments/           MLflow experiments (pod failure, log anomaly, cost)
  serving/               KServe + FastAPI deployment manifests
aiops/
  n8n-workflows/         Exported n8n workflow JSONs
  policies/              OPA Rego + Kyverno YAML policies
  falco/                 Falco custom rules
observability/
  dashboards/grafana/    10 Grafana dashboard JSONs
  alerts/                Prometheus rules + Alertmanager config
  otel/                  OTEL collector config
data/synthetic/          5 deterministic synthetic data generators
eval/                    Unified eval framework (metrics.py + scorer.py)
portal/                  HuggingFace Spaces Gradio app (opt-in)
backstage/               catalog-info.yaml (entity lint only)
scripts/                 setup-dagshub.sh, setup-kind.sh, etc.
```

## Eval Framework

Every UC workflow ends with an eval gate. A score below threshold fails CI:

```python
# All thresholds in eval/scorer.py
# Example: UC1 drift detection must score >= 70/100
# The composite score weights precision, recall, integration checks
```

Results are written to `eval-results/` as JSON and published to GitHub Pages.

## Technology Stack

**Core MLOps**: MLflow · Feast · DVC · Apache Airflow · Kubeflow Pipelines · KServe · FastAPI

**AIOps**: n8n · Qdrant · Ollama/TinyLlama · LangChain · Falco · OPA

**Observability**: OpenTelemetry · Prometheus · Grafana · Loki · Tempo · FluentBit · Alertmanager

**Drift & Monitoring**: Evidently AI · NannyML · Alibi Detect · WhyLogs · WhyLabs

**ML Libraries**: PyTorch · scikit-learn · NumPy · Pandas · Prophet · Optuna · SHAP · sentence-transformers · scipy

**Security**: Trivy · Falco · Kyverno · OPA · SBOM (CycloneDX)

**Infrastructure**: Kubernetes (Kind) · Helm · KEDA · Karpenter (ref) · Terraform (ref) · Crossplane (ref)

## License

MIT
