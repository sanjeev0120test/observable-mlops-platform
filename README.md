# Observable MLOps Platform

Enterprise-grade **AIOps + MLOps** reference platform for SaaS teams. **23 use cases**, each with a blocking CI eval gate. **Zero local runtime required** — everything validates in GitHub Actions using ephemeral Docker Compose and Kind clusters.

**Live repo**: [github.com/sanjeev0120test/observable-mlops-platform](https://github.com/sanjeev0120test/observable-mlops-platform)  
**MLflow/DVC remote**: [dagshub.com/sanjeev0120test/observable-mlops-platform](https://dagshub.com/sanjeev0120test/observable-mlops-platform)  
**Eval portal**: `https://sanjeev0120test.github.io/observable-mlops-platform/` (after `91-publish-portal` runs)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Thinking](#system-thinking)
3. [Observability Strategy](#observability-strategy)
4. [23 Use Cases — Business Value & ROI](#23-use-cases--business-value--roi)
5. [Implementation Phases (Complete)](#implementation-phases-complete)
6. [Validation — Run Everything at Once](#validation--run-everything-at-once)
7. [Your Action Items](#your-action-items)
8. [Architecture Decisions (Why We Chose This)](#architecture-decisions-why-we-chose-this)
9. [Repository Structure](#repository-structure)
10. [Eval Framework](#eval-framework)
11. [Technology Stack](#technology-stack)
12. [Troubleshooting](#troubleshooting)

---

## Executive Summary

This platform solves **23 distinct enterprise pain points** spanning ML lifecycle management, operational intelligence, security, and developer productivity. Each use case is:

- **Isolated** in its own workflow and folder (easy to adopt piecemeal)
- **Measured** by a unified eval framework (`eval/metrics.py` + `eval/scorer.py`)
- **Gated** in CI — scores below threshold block the workflow
- **Observable** — critical paths emit metrics, logs, and traces through OpenTelemetry → Prometheus / Loki / Tempo

**Typical ROI for a mid-size SaaS org (500–2,000 engineers, $5–20M/year infra spend):**

| Category | Annual savings (conservative) | Primary UCs |
|---|---|---|
| Incident reduction (MTTR, alert fatigue) | $400K–$1.2M | UC2, UC3, UC6, UC8, UC11, UC21 |
| ML model reliability (drift, skew, retrain) | $200K–$800K | UC1, UC5, UC9, UC19, UC22 |
| Cloud cost optimization | $150K–$600K | UC4, UC10, UC18 |
| Security & compliance automation | $100K–$400K | UC7, UC12, UC17, UC20 |
| Engineering velocity (DORA, catalog, HPO) | $150K–$500K | UC14, UC15, UC20, UC23 |

*Estimates assume 30–50% reduction in P1 incidents, 15–25% infra waste recovery, and 20–40% faster model promotion cycles. Adjust for your scale.*

---

## System Thinking

### The problem space

Enterprise SaaS teams run three overlapping planes that traditionally silo:

```
┌─────────────────────────────────────────────────────────────────┐
│  BUSINESS PLANE    SLOs, cost, DORA, compliance, catalog      │
├─────────────────────────────────────────────────────────────────┤
│  ML PLANE          Features, training, drift, serving, explain  │
├─────────────────────────────────────────────────────────────────┤
│  OPS PLANE         Logs, metrics, traces, alerts, self-heal    │
└─────────────────────────────────────────────────────────────────┘
```

When these planes don't share signals, you get: **silent model drift**, **alert storms**, **manual runbooks**, **uncontrolled cloud spend**, and **slow incident response**.

### Our approach: closed-loop observability + eval gates

```
Synthetic/Real Data → ML/AIOps Pipeline → Metrics + Artifacts
         │                                        │
         ▼                                        ▼
   GitHub Actions UC Workflow              OTEL → Prom/Loki/Tempo
         │                                        │
         ▼                                        ▼
   eval/scorer.py (blocking gate)         Alertmanager → n8n/OPA
         │                                        │
         └──────────────► eval-results/ ◄─────────┘
                              │
                              ▼
                    90-e2e → 91-portal (GitHub Pages)
```

**Key insight**: Every UC workflow *proves* its value numerically before merging. Observability is not bolted on — alert rules in `observability/alerts/rules/platform.yml` are tagged with `uc: UCx` and validated in CI (`01-observability`, `00-pr-validate`).

### Execution model (no local machine)

| Layer | Technology | Why |
|---|---|---|
| CI orchestrator | GitHub Actions | Free for public repos; auditable; no laptop dependency |
| Ephemeral ML stack | Docker Compose Stack A | MLflow, Feast, Airflow, Redis, Qdrant, n8n |
| Ephemeral observability | Docker Compose Stack B | Prometheus, Grafana, Loki, Tempo, OTEL Collector |
| Ephemeral K8s | Kind (in-job) | KServe, Kyverno, KEDA, OPA admission |
| Persistence | DagsHub | MLflow tracking + DVC remote (one token) |
| Reports | GitHub Pages | Drift reports, eval scorecards, portal |

---

## Observability Strategy

Production-grade observability follows the **three pillars**, unified by OpenTelemetry:

| Pillar | Tool | What it captures | Critical UCs |
|---|---|---|---|
| **Metrics** | Prometheus + Grafana | SLO burn, PSI drift, CPU, cost waste | UC1, UC4, UC10, UC15, UC21 |
| **Logs** | Loki + FluentBit | Container logs, anomaly patterns | UC2, UC16 |
| **Traces** | Tempo + OTEL | Request paths, RCA latency | UC11, UC18 |

### UC → observability mapping (validated in CI)

| UC | Signal | Alert / Dashboard | Workflow validation |
|---|---|---|---|
| UC1 | `ml_model_psi_score` | `MLModelDriftDetected` | `03-drift-detection` |
| UC2 | Log patterns + restarts | `PodCrashLoopBackOff` | `04-log-anomaly` |
| UC3 | Alert count | Grafana "Active Alerts" panel | `06-alert-correlation` |
| UC4 | CPU utilization | `HighCPUPreScale` → KEDA | `07-predictive-scaling` |
| UC6 | Falco + policy events | Alertmanager → n8n (UC6 route) | `08-self-healing` |
| UC10 | `cloud_cost_waste_ratio` | `IdleResourceWaste` | `11-cost-optimizer` |
| UC21 | HTTP error rate | `SLOFastBurnRate` / `SLOSlowBurnRate` | `15-slo-monitoring` |
| UC23 | Incident webhook | Alertmanager → n8n (UC23 route) | `09-rag-runbook` |

**Static checks** (`00-pr-validate` → `observability-coverage-check`):
- Critical UCs UC1, UC2, UC4, UC10, UC21 have Prometheus alert rules
- OTEL exports traces → Tempo, logs → Loki, metrics → Prometheus
- Grafana overview dashboard panels reference UC21, UC1, UC10, UC3

**Runtime checks** (`01-observability`):
- Full Stack B starts in CI (Prometheus, Grafana, Loki, Tempo, OTEL)
- Health probes + datasource validation + test OTLP span
- UC-tagged alert rule inventory + Alertmanager routing verified live

### OTEL collector pipeline

```
App/CI  ──OTLP──►  otel-collector  ──►  Tempo (traces)
                              ├──►  Loki (logs)
                              └──►  Prometheus (metrics via remote write)
```

Config: `observability/otel/otelcol.yml`  
Rules: `observability/alerts/rules/platform.yml`  
Dashboard: `observability/dashboards/grafana/overview.json`

---

## 23 Use Cases — Business Value & ROI

| UC | Problem (enterprise pain) | Solution | Tools | Typical impact |
|---|---|---|---|---|
| **UC1** | Model silently degrades in production | Drift detection + auto-retrain DAG | Evidently, NannyML, Alibi, Airflow | **30–50% fewer bad predictions**; retrain within hours not weeks |
| **UC2** | Log floods hide real incidents | LSTM log anomaly detection | PyTorch, Loki, Qdrant | **40–60% faster anomaly detection** vs keyword rules |
| **UC3** | Alert fatigue (100s of duplicate pages) | DBSCAN alert correlation | sklearn, Prometheus | **50–70% alert volume reduction** (industry avg for dedup) |
| **UC4** | Reactive scaling wastes money or causes outages | Prophet forecast + KEDA pre-scale | Prophet, KEDA, Prometheus | **15–25% compute savings**; fewer latency spikes |
| **UC5** | Training-serving skew causes silent errors | Feast offline/online compare | Feast, GE, Evidently | **Catches skew before production**; standard MLOps hygiene |
| **UC6** | Manual incident response at 3 AM | OPA-gated self-healing + n8n | OPA, Falco, n8n | **MTTR −30–50%** for allowed auto-actions |
| **UC7** | CVEs and policy drift in containers | Trivy + Falco + Kyverno + OPA | Trivy, Falco, Kyverno | **Blocks vulnerable images**; audit trail for compliance |
| **UC8** | Engineers search Confluence during incidents | RAG runbook Q&A | Qdrant, sentence-transformers | **5–15 min saved per incident** lookup |
| **UC9** | No experiment lineage or safe promotion | MLflow registry + OPA promotion gate | MLflow, DVC, OPA | **Audit-ready model promotion** |
| **UC10** | Cloud bill surprises | IsolationForest cost anomalies | sklearn, Prometheus | **10–20% waste identified** in idle resources |
| **UC11** | Can't trace root cause across services | OTEL + Tempo RCA | OTEL, Tempo, Grafana | **RCA time −25–40%** with trace correlation |
| **UC12** | GitOps config drift | Kyverno + OPA compliance check | Kyverno, OPA | **Prevents config drift** before deploy |
| **UC13** | Bad data reaches training | Great Expectations gates | GE, Airflow | **Data incidents −60%+** at pipeline boundary |
| **UC14** | Manual hyperparameter tuning | Optuna + MLflow HPO | Optuna, MLflow | **2–5× faster** to optimal hyperparams |
| **UC15** | No engineering metrics visibility | DORA four keys from GHA | Prometheus, Grafana | **Visibility → 10–20% deploy freq improvement** |
| **UC16** | Errors mis-routed to wrong team | Embedding-based classification | sklearn, sentence-transformers | **Routing accuracy 85%+** |
| **UC17** | Regulated models lack explainability | SHAP + MLflow audit | SHAP, MLflow, OPA | **Compliance-ready** model documentation |
| **UC18** | Reactive rate limits cause 429 storms | Predictive rate limiting | Redis, sklearn, KEDA | **429 errors −20–40%** during traffic spikes |
| **UC19** | Feature distribution drift undetected | WhyLogs profiling | WhyLogs | **Early warning** before model impact |
| **UC20** | No service ownership map | Backstage catalog validation | catalog-info.yaml | **Onboarding time −30%** with clear ownership |
| **UC21** | SLO breaches discovered too late | Error budget + fast-burn alerts | Prometheus, Grafana | **SLO compliance visibility**; burn alerts in 2 min |
| **UC22** | Risky model rollouts | KServe canary + A/B stats | KServe, scipy | **Safe promotion** with statistical gate |
| **UC23** | Post-mortems are manual and slow | Auto post-mortem + GitHub Issue | n8n, Qdrant, TinyLlama | **Post-mortem draft in minutes** not hours |

### Workflow reference

| Workflow file | UC(s) |
|---|---|
| `00-pr-validate.yml` | Platform lint + eval framework |
| `01-observability.yml` | Stack B health + UC alert coverage |
| `02-data-pipeline.yml` | Data foundation (DVC + GE) |
| `03-drift-detection.yml` | UC1 |
| `04-log-anomaly.yml` | UC2 |
| `05-feature-skew.yml` | UC5 |
| `06-alert-correlation.yml` | UC3 |
| `07-predictive-scaling.yml` | UC4 |
| `08-self-healing.yml` | UC6 |
| `09-rag-runbook.yml` | UC8, UC23 |
| `10-model-serving.yml` | UC9, UC17, UC22 |
| `11-cost-optimizer.yml` | UC10 |
| `13-security-policy.yml` | UC7 |
| `14-dora-metrics.yml` | UC15 |
| `15-slo-monitoring.yml` | UC21 |
| `18-distributed-tracing.yml` | UC11 |
| `19-gitops-drift.yml` | UC12 |
| `20-data-quality.yml` | UC13 |
| `21-hpo.yml` | UC14 |
| `22-error-classification.yml` | UC16 |
| `23-explainability.yml` | UC17 |
| `24-rate-limiting.yml` | UC18 |
| `25-feature-monitoring.yml` | UC19 |
| `26-catalog-validate.yml` | UC20 |
| `90-e2e-integration.yml` | All UC eval aggregation |
| `91-publish-portal.yml` | GitHub Pages portal |

---

## Implementation Phases (Complete)

All phases are implemented. Validation is designed to run **after all phases** via `90-e2e-integration` + portal publish.

| Phase | Scope | Status | Key artifacts |
|---|---|---|---|
| **0** | Repo scaffold, eval framework, lint CI | ✅ Done | `eval/`, `00-pr-validate` |
| **1** | Observability stack (OTEL, Prom, Grafana, Loki, Tempo) | ✅ Done | `01-observability`, `observability/` |
| **2** | Data pipeline + synthetic generators | ✅ Done | `02-data-pipeline`, `data/synthetic/` |
| **3** | Core ML ops (drift, logs, features, alerts) | ✅ Done | UC1–UC5 workflows |
| **4** | AIOps (self-heal, RAG, security) | ✅ Done | UC6–UC8, UC7 |
| **5** | Model lifecycle (serving, cost, tracing, gitops) | ✅ Done | UC9–UC12, UC10–UC11 |
| **6** | Platform maturity (DORA, SLO, HPO, catalog, portal) | ✅ Done | UC13–UC23, `90`, `91` |

**Nothing is missing from the original 23-UC plan.** Optional enhancements (not required for green CI):

- HuggingFace Spaces portal (`HF_TOKEN`)
- WhyLabs cloud dashboard (`WHYLABS_API_KEY` + `WHYLABS_ORG_ID`)
- Production EKS/GKE deploy (Terraform reference in `infra/terraform/`)

---

## Validation — Run Everything at Once

### Recommended: full platform validation (GitHub Actions only)

```bash
# 1. Clone (or use your fork)
git clone https://github.com/sanjeev0120test/observable-mlops-platform.git
cd observable-mlops-platform

# 2. Ensure secrets are set (see "Your Action Items" below)

# 3. Dispatch ALL workflows + E2E aggregation
bash scripts/run-all-workflows.sh

# 4. Monitor progress
gh run list --limit 30

# 5. After workflows complete, check E2E summary
gh run download $(gh run list --workflow=90-e2e-integration.yml --limit=1 --json databaseId -q '.[0].databaseId')
cat eval-results/summary.json

# 6. View portal (after 91-publish-portal succeeds)
# https://<your-org>.github.io/observable-mlops-platform/
```

### Single-workflow dispatch

```bash
gh workflow run 03-drift-detection.yml --ref main
gh workflow run 01-observability.yml --ref main
gh workflow run 90-e2e-integration.yml --ref main
```

### What "green" means

| Check | Pass criteria |
|---|---|
| Each UC workflow | Eval score ≥ threshold in `eval/metrics.py` |
| `00-pr-validate` | Lint + structure + 23 UC registry + observability static check |
| `01-observability` | Stack B healthy + critical UC alerts present |
| `90-e2e-integration` | Aggregates all available `eval-results/uc*.json` |
| `91-publish-portal` | GitHub Pages deploys; HF upload skipped if no token |

---

## Your Action Items

### Required (one-time setup)

| Step | Action | Where |
|---|---|---|
| 1 | **Set `DAGSHUB_TOKEN`** | GitHub → Settings → Secrets → Actions |
| 2 | Create DagsHub repo (if not done) | [dagshub.com/sanjeev0120test/observable-mlops-platform](https://dagshub.com/sanjeev0120test/observable-mlops-platform) |
| 3 | Enable **GitHub Pages** (source: `gh-pages` branch) | GitHub → Settings → Pages |
| 4 | Run full validation | `bash scripts/run-all-workflows.sh` |

**How to create DagsHub token:**
1. Go to [dagshub.com/user/settings/tokens](https://dagshub.com/user/settings/tokens)
2. Create token with repo read/write scope
3. Add as `DAGSHUB_TOKEN` in GitHub Secrets
4. Never commit the token to git (`.env*` is gitignored)

### Optional (unlocks extra features)

| Secret | Enables |
|---|---|
| `HF_TOKEN` | HuggingFace Hub artifact upload + Spaces portal mirror |
| `WHYLABS_API_KEY` + `WHYLABS_ORG_ID` | WhyLabs cloud dashboard for UC19 |
| `HF_SPACE_NAME` (repo variable) | Custom HF Space name (default: `observable-mlops-platform`) |

### You do NOT need to

- Install Python, Docker, or Kubernetes locally
- Run any workflow on your Windows/Mac machine
- Commit secrets or `.env.local` files

---

## Architecture Decisions (Why We Chose This)

| Decision | Choice | Reason | Alternative rejected |
|---|---|---|---|
| CI-only execution | GitHub Actions | Zero local deps; reproducible; auditable | Local docker-compose dev (user constraint) |
| ML experiment tracking | MLflow on DagsHub | Free tier; git-native; DVC remote included | Self-hosted MLflow (ops overhead) |
| Feature store | Feast (file + Redis) | Industry standard; offline/online skew testable | Custom feature cache (not portable) |
| Observability | OTEL + Prom/Grafana/Loki/Tempo | CNCF standard; single collector fan-out | ELK-only (no native traces) |
| Policy engine | OPA (Rego) | Portable; testable in CI without K8s | Hard-coded if/else (not auditable) |
| K8s in CI | Kind ephemeral | Real KServe/Kyverno/KEDA behavior | Mock K8s API (unrealistic) |
| Vector DB | Qdrant | Lightweight; runs in Compose; good for RAG | Pinecone (paid; external dep) |
| LLM | TinyLlama via Ollama | Small; runs in CI; no API cost | GPT-4 API (cost + secret in CI) |
| Workflow automation | n8n | Visual; webhook-native; self-hosted in Compose | Temporal (heavier infra for this scope) |
| Eval gating | Custom `eval/scorer.py` | Unified thresholds across 23 UCs; blocks bad merges | Per-workflow ad-hoc asserts (inconsistent) |
| Drift tools | Evidently + NannyML + Alibi | Complementary: statistical + performance + multivariate | Single tool (blind spots) |
| Security scanning | Trivy + Falco + Kyverno | Image + runtime + admission — defense in depth | Snyk-only (narrower scope) |

---

## Repository Structure

```
.github/workflows/       26 workflow files (00-26 + 90-91)
infra/
  docker-compose/        Stack A (ML/data) + Stack B (observability)
  kind/                  Kind cluster configs
  helm/                  Helm values reference
  terraform/             Reference IaC (aws-eks, gcp-gke)
services/                Per-UC microservices (FastAPI)
mlops/
  feature-store/         Feast definitions
  pipelines/             Airflow DAGs + Kubeflow pipelines
  experiments/           Training scripts
  serving/               KServe + FastAPI manifests
aiops/
  n8n-workflows/         Exported workflow JSONs
  policies/              OPA Rego + Kyverno YAML
  falco/                 Runtime security rules
observability/
  dashboards/grafana/    Platform overview dashboard
  alerts/                Prometheus rules + Alertmanager
  otel/                  OTEL collector config
data/synthetic/          Deterministic data generators (5 scripts)
eval/                    Unified eval framework
portal/                  GitHub Pages portal source
backstage/               Service catalog (27 entities)
scripts/                 setup-dagshub.sh, run-all-workflows.sh, etc.
```

---

## Eval Framework

Every UC workflow ends with `run_eval_gate()`:

```python
from eval.scorer import run_eval_gate
run_eval_gate("UC1", {"psi_score": 1.2, "ks_statistic": 0.45, ...}, Path("eval-results"))
# Exits 1 if composite score < threshold → blocks CI
```

- **Thresholds**: `eval/metrics.py` → `THRESHOLDS` dict (per-UC, 50–90 range)
- **Metrics**: `UC_METRICS` dict defines direction (`higher_better`, `lower_better`, `bool_true`, `exact`) and weights
- **Output**: `eval-results/uc1.json`, `uc2.json`, … + `summary.json` from workflow 90

---

## Technology Stack

**MLOps**: MLflow · Feast · DVC · Airflow · Kubeflow · KServe · Optuna · SHAP  
**AIOps**: n8n · Qdrant · Ollama/TinyLlama · LangChain · Falco · OPA  
**Observability**: OpenTelemetry · Prometheus · Grafana · Loki · Tempo · FluentBit · Alertmanager  
**Drift/Monitoring**: Evidently · NannyML · Alibi Detect · WhyLogs  
**ML**: PyTorch · scikit-learn · NumPy · Pandas · Prophet · sentence-transformers  
**Security**: Trivy · Falco · Kyverno · OPA  
**Infra**: Docker Compose · Kind · Helm · KEDA · Terraform (ref)

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `DAGSHUB_TOKEN` errors in MLflow steps | Secret not set | Add secret; workflow continues with `continue-on-error` where non-critical |
| `91-publish-portal` HF failure | Empty `HF_TOKEN` | Fixed — skips gracefully; or add token |
| UC5 Feast materialize warning | Timestamp tz in parquet | Non-blocking (`continue-on-error`); skew eval still runs |
| E2E shows missing UCs | Not all workflows run yet | `bash scripts/run-all-workflows.sh` |
| OPA test failures | Input JSON wrapper for `opa eval -i` | Input file IS the document (no `{"input":{}}` wrapper) |
| Portal 404 | Pages not enabled | Enable GitHub Pages on `gh-pages` branch |

---

## License

MIT
