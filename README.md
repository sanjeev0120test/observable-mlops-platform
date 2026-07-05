# Observable MLOps Platform

An enterprise-grade **AIOps + MLOps** reference platform built the way senior engineers at
hyperscalers do it: **closed-loop, policy-gated, observable, and fail-safe by default**.
It packages **23 use cases** across the full ML/Ops lifecycle — from drift detection and
alert correlation to self-healing, RAG runbooks, and cost optimization — each backed by a
**blocking CI eval gate** so correctness is *proven*, never assumed.

- **Repo:** <https://github.com/sanjeev0120test/observable-mlops-platform>
- **MLflow / DVC remote:** <https://dagshub.com/sanjeev0120test/observable-mlops-platform>
- **Eval portal:** published by `91-publish-portal.yml` after every CI run

> **CI status:** all 29 workflows green — 23 UC eval gates + lint/structure (ruff, black,
> actionlint), 101 unit tests, 30 OPA policy tests, chaos/k8s manifest validation, SBOM
> signing, and end-to-end score aggregation. Every use case must clear its numeric threshold
> before a commit lands on `main`.

---

## 1. What this is

A *system of systems* that wires production reliability patterns into a feedback loop:

```
observe  →  orient  →  decide  →  act  →  verify  →  observe …
UC1/UC2     UC3/UC11   OPA/SLO    UC6/UC4   eval gates
drift/log   correlate  policy     remediate/scale    Prometheus + CI
```

Every use case is isolated in its own folder and GitHub Actions workflow so you can
adopt any single piece without taking the whole platform.

---

## 2. Why it exists — failure modes this platform eliminates

| Failure mode in the wild | Pattern applied here | Where |
|---|---|---|
| "Works in the demo" but never measured | Blocking **eval gates** in every workflow | `eval/`, all `*.github/workflows/*` |
| Autonomous actions with no guardrails | **Fail-closed** OPA policy engine | `services/self-healing/`, `aiops/policies/opa/` |
| A dependency blip triggers wrong actions | **Retry + circuit breaker + idempotency** | `services/self-healing/src/resilience.py` |
| Models promoted without validation | **Shadow mode + promotion gate** | `platform/shadow-mode/` |
| Reliability claims never stress-tested | **Chaos engineering + k6 load tests** | `platform/chaos/`, `tests/load/` |
| LLM answers hallucinate or get injected | **RAG hardening** (sanitize, ground, defend) | `services/runbook-agent/src/main.py` |
| Insecure workloads admitted to the cluster | Non-root images, NetworkPolicy, Kyverno, Trivy, SBOM | `infra/kubernetes/`, `aiops/policies/kyverno/` |
| Alert storms bury real incidents | **DBSCAN correlation** with FPR gate | `services/alert-correlator/` |

---

## 3. Core design invariants

1. **Value is CI-proven** — every UC writes structured metrics that must clear a numeric threshold in `eval/scorer.py`; the job exits 1 on failure.
2. **Fail-closed by default** — if OPA is unreachable, remediation returns HTTP 503; it is never allowed through.
3. **Control plane ≠ data plane** — policy decisions (OPA, SLO budgets) are separated from execution (inference, scale, remediate).
4. **Blast-radius containment** — namespace allowlists, replica caps, canary splits, error budgets, and PodDisruptionBudgets.
5. **Single source of truth** — Git for config, MLflow + DagsHub for experiments, Backstage for the service catalog; controllers reconcile to declared state.

---

## 4. Architecture

```mermaid
flowchart LR
  subgraph Observe
    A[drift-monitor\nUC1] ; B[anomaly-detector\nUC2] ; C[alert-correlator\nUC3]
  end
  subgraph Decide
    O[OPA policies\nfail-closed] ; S[SLOs / error budget\nUC21]
  end
  subgraph Act
    H[self-healing UC6\nretry+CB+idempotency] ; P[predictive-scaler UC4\nshadow mode]
  end
  subgraph Knowledge
    K[runbook-agent UC8\nRAG hardened] ; Q[(Qdrant)]
  end
  A --> C --> O --> H
  B --> C
  P --> O
  S --> H
  K --- Q
  H -->|metrics| M[(Prometheus / Grafana / Tempo / Loki)]
  P -->|metrics| M
```

---

## 5. Project structure

Complete map of every folder and file, one line per entry, explaining **what it is and why it exists**.

```text
observable-mlops-platform/
│
├── .github/workflows/                     # All CI — 29 numbered workflows + aggregation + portal
│   ├── 00-pr-validate.yml                 # Gate 0: ruff, black, actionlint, OPA tests, structure checks
│   ├── 01-observability.yml               # Gate: Stack B health + alert rule inventory (Prometheus/Grafana/Loki/Tempo)
│   ├── 02-data-pipeline.yml               # Gate: DVC repro + Great Expectations data quality
│   ├── 03-drift-detection.yml             # Gate UC1: KS/PSI/NannyML/Alibi drift metrics
│   ├── 04-log-anomaly.yml                 # Gate UC2: LSTM autoencoder reconstruction error
│   ├── 05-feature-skew.yml                # Gate UC5: Feast feature store train/serve skew
│   ├── 06-alert-correlation.yml           # Gate UC3: DBSCAN dedup rate / silhouette / FPR
│   ├── 07-predictive-scaling.yml          # Gate UC4: Prophet / linear trend forecast accuracy
│   ├── 08-self-healing.yml                # Gate UC6: OPA policy decisions + eval gate
│   ├── 09-rag-runbook.yml                 # Gate UC8/UC23: RAG retrieval + groundedness score
│   ├── 10-model-serving.yml               # Gate UC9/UC22: canary + A/B promotion eval
│   ├── 11-cost-optimizer.yml              # Gate UC10: IsolationForest cost anomaly F1/precision
│   ├── 13-security-policy.yml             # Gate UC7: Trivy CVE scan + Falco rule count + Kyverno
│   ├── 14-dora-metrics.yml                # Gate UC15: DORA 4 Keys from GHA events
│   ├── 15-slo-monitoring.yml              # Gate UC21: SLO burn-rate rule validation
│   ├── 18-distributed-tracing.yml         # Gate UC11: OTEL span coverage + Tempo query
│   ├── 19-gitops-drift.yml                # Gate UC12: Kyverno + OPA compliance drift check
│   ├── 20-data-quality.yml                # Gate UC13: Great Expectations expectation suite pass rate
│   ├── 21-hpo.yml                         # Gate UC14: Optuna best trial F1 above threshold
│   ├── 22-error-classification.yml        # Gate UC16: sklearn sentence-transformer error classifier
│   ├── 23-explainability.yml              # Gate UC17: SHAP explanation count + fidelity
│   ├── 24-rate-limiting.yml               # Gate UC18: Redis + sklearn predictive rate limiter precision
│   ├── 25-feature-monitoring.yml          # Gate UC19: WhyLogs drift profile completeness
│   ├── 26-catalog-validate.yml            # Gate UC20: Backstage catalog entity schema validation
│   ├── 27-unit-tests.yml                  # Runs all pytest unit suites + OPA policy tests
│   ├── 28-sbom-signing.yml                # Syft SBOM generation + Trivy SARIF + Cosign signing
│   ├── 29-resilience-chaos.yml            # Validates chaos/k8s manifests + unit tests for resilience/shadow/RAG
│   ├── 90-e2e-integration.yml             # Aggregates all UC eval JSON results; exits 1 if any UC fails
│   └── 91-publish-portal.yml              # Publishes eval scores to GitHub Pages after successful runs
│
├── aiops/                                 # Policy-as-code and runtime security
│   ├── falco/
│   │   └── custom_rules.yml               # Falco runtime threat rules (crypto miner, shell in container, etc.)
│   ├── n8n-workflows/
│   │   └── self-healing-workflow.json     # n8n automation: Alertmanager webhook → self-healing API call
│   └── policies/
│       ├── kyverno/
│       │   ├── disallow-privileged.yml    # Kyverno policy: block privileged containers cluster-wide
│       │   └── require-labels.yml         # Kyverno policy: require app/team/uc labels on all pods
│       └── opa/
│           ├── self_healing.rego          # OPA: allow/deny remediation (namespace protection, replica cap)
│           ├── self_healing_test.rego     # OPA unit tests for self_healing.rego (30 test cases)
│           ├── model_promotion.rego       # OPA: allow/deny model version promotion (accuracy + bias gates)
│           └── model_promotion_test.rego  # OPA unit tests for model_promotion.rego
│
├── backstage/                             # Software catalog (internal developer portal)
│   ├── docs/                              # TechDocs source for Backstage
│   └── catalog-info.yaml                 # Backstage entity definitions for all services
│
├── data/
│   ├── synthetic/                         # Deterministic synthetic data generators (seeded, reproducible)
│   │   ├── generate_alerts.py             # Prometheus alert stream with correlated cascades (UC3)
│   │   ├── generate_container_logs.py     # Container log stream with injected anomalies (UC2)
│   │   ├── generate_cost_data.py          # Cloud cost timeseries with anomaly spikes (UC10)
│   │   ├── generate_http_traffic.py       # HTTP request timeseries for SLO/rate-limit testing (UC18/UC21)
│   │   └── generate_pod_metrics.py        # Pod CPU/memory metrics for drift + prediction (UC1/UC4)
│   └── dvc.yaml                           # DVC pipeline: generators → parquet artifacts → tracked by DVC
│
├── docs/
│   └── images/
│       └── local-observability-lab/       # 51 validation screenshots from 2026-06-11 local session
│           └── 01.png … 51.png            # See "Local Observability Lab" section below for full index
│
├── eval/                                  # Unified eval framework used by all 23 UC workflows
│   ├── metrics.py                         # MetricSpec per UC: direction (higher/lower/bool), weight, threshold
│   └── scorer.py                          # compute_score() → weighted composite [0–100]; run_eval_gate() exits 1
│
├── governance/
│   └── eu-ai-act/
│       └── compliance_check.py            # Static checks: model card present, bias metrics logged, audit trail
│
├── infra/
│   ├── crossplane/                        # Crossplane XRD/Composition scaffold (cloud resource abstraction)
│   ├── docker-compose/
│   │   ├── config/
│   │   │   ├── fluent-bit.conf            # Fluent Bit log collection → Loki pipeline config
│   │   │   ├── loki.yml                   # Loki storage + schema config (filesystem, single-binary)
│   │   │   └── tempo.yml                  # Tempo trace storage config (local backend)
│   │   ├── grafana-provisioning/
│   │   │   └── datasources.yml            # Auto-provisions Prometheus/Loki/Tempo datasources in Grafana
│   │   ├── init-scripts/
│   │   │   └── postgres-init-dbs.sh       # Creates MLflow + Airflow databases in Postgres on first boot
│   │   ├── docker-compose.mlops-core.yml  # Stack A: MLflow, Postgres, Redis, Airflow, Qdrant, n8n
│   │   ├── docker-compose.observability.yml # Stack B: Prometheus, Grafana, Loki, Tempo, OTEL, Alertmanager
│   │   └── docker-compose.services.yml    # Stack C: all FastAPI microservices (build from ./services/*)
│   ├── helm/
│   │   ├── falco/values.yaml              # Falco Helm values: custom rule path, Prometheus metrics enabled
│   │   ├── keda/values.yml                # KEDA Helm values: scaler config, Prometheus metrics adapter
│   │   ├── kserve/values.yml              # KServe Helm values: InferenceService defaults, canary split
│   │   ├── kubeflow/                      # Kubeflow Helm scaffold (Pipeline + Katib components)
│   │   └── kyverno/values.yml             # Kyverno Helm values: enforcement mode, webhook config
│   ├── kind/
│   │   ├── pipelines-cluster.yml          # Kind config: Airflow/Kubeflow training cluster (multi-node)
│   │   ├── policy-cluster.yml             # Kind config: OPA/Kyverno policy validation cluster
│   │   └── serving-cluster.yml            # Kind config: KServe model serving cluster
│   ├── kubernetes/base/
│   │   └── self-healing/                  # Production-hardened k8s manifests for self-healing service
│   │       ├── deployment.yaml            # Non-root, read-only fs, CPU/memory limits, probes
│   │       ├── networkpolicy.yaml         # Default-deny; allow OPA egress + Prometheus/n8n ingress only
│   │       ├── pdb.yaml                   # PodDisruptionBudget: minAvailable=1 (survives node drain)
│   │       └── kustomization.yaml         # Kustomize entry point for the self-healing base overlay
│   └── terraform/
│       ├── aws-eks/                       # Terraform scaffold: EKS cluster + node groups + IRSA
│       └── gcp-gke/                       # Terraform scaffold: GKE Autopilot cluster
│
├── llmops/
│   └── ragas/
│       └── ragas_eval.py                  # RAGAS-style offline eval: faithfulness + context recall for UC8
│
├── mlops/
│   ├── experiments/
│   │   ├── cost_anomaly/                  # IsolationForest training script (UC10) — logged to MLflow
│   │   ├── log_anomaly/
│   │   │   └── lstm_autoencoder.py        # LSTM autoencoder for log sequence anomaly detection (UC2)
│   │   └── pod_failure_prediction/
│   │       └── train.py                   # GradientBoostingClassifier for pod failure prediction (UC9)
│   ├── feature-store/
│   │   └── feature_repo/
│   │       ├── feature_store.yaml         # Feast project config: registry path, online/offline store
│   │       └── features.py                # Feast FeatureView definitions: pod metrics, HTTP features
│   ├── pipelines/
│   │   ├── airflow/dags/
│   │   │   └── pod_failure_prediction_retrain.py # Drift-triggered Airflow DAG: detect → retrain → register
│   │   └── kubeflow/
│   │       ├── components/                # KFP v2 component YAML: data_validation, feature_engineering, eval
│   │       └── pipelines/                 # KFP v2 pipeline definition (end-to-end training pipeline)
│   └── serving/
│       ├── fastapi/                       # FastAPI serving scaffold (fallback when KServe unavailable)
│       └── kserve/                        # KServe InferenceService manifests for pod-failure model
│
├── observability/
│   ├── alerts/
│   │   ├── rules/platform.yml             # Prometheus alerting rules tagged by UC (uc: UC1 … UC23)
│   │   ├── alertmanager.yml               # Alertmanager routing: severity → webhook (UC6/n8n) or PagerDuty
│   │   └── prometheus.yml                 # Prometheus scrape config: all service + infra targets
│   ├── dashboards/grafana/
│   │   ├── dashboard.yaml                 # Grafana provisioning sidecar config (file-based dashboard load)
│   │   └── overview.json                  # Platform Overview dashboard: health, PSI, SLO, cost, alerts panels
│   └── otel/
│       └── otelcol.yml                    # OTEL Collector pipeline: OTLP receive → Prometheus/Tempo/Loki export
│
├── platform/                              # Cross-cutting capabilities shared across UCs
│   ├── chaos/
│   │   ├── opa-unavailable.yaml           # Chaos Mesh: partition OPA network; verifier confirms self-healing stays 503
│   │   ├── memory-and-pod-resilience.yaml # Chaos Mesh + Litmus: memory hog on drift-monitor, pod-kill on self-healing
│   │   └── redis-latency.yaml             # Chaos Mesh: inject 200ms latency on Redis for rate-limiter testing
│   ├── logging/
│   │   └── structured_logger.py           # Shared JSON structured logging helper (trace_id, uc, service fields)
│   ├── rollback/
│   │   └── auto_rollback.py               # OPA-gated model rollback: checks promotion policy before switching
│   ├── shadow-mode/
│   │   ├── shadow_evaluator.py            # Binary + forecast evaluators with fail-safe promotion gates
│   │   └── kserve-shadow.yaml             # KServe InferenceService traffic mirror (shadow → 0% production traffic)
│   └── slo-definitions/
│       └── platform-slos.yaml             # SLO definitions: error_rate < 1%, p99 < 500ms, availability > 99.9%
│
├── portal/                                # Static eval portal published to GitHub Pages (auto-generated)
│
├── scripts/
│   ├── publish-portal.sh                  # Generates portal HTML from eval-results JSON artifacts
│   ├── run-all-workflows.sh               # Manually dispatches all 29 workflows (CI warm-up or recovery)
│   ├── setup-dagshub.sh                   # Configures DagsHub remote for DVC + MLflow (uses DAGSHUB_TOKEN)
│   ├── setup-kind.sh                      # Creates Kind clusters from infra/kind/*.yml configs
│   ├── setup-ollama.sh                    # Pulls TinyLlama model for local RAG runbook agent testing
│   └── validate_data.py                   # Great Expectations data validation suite runner
│
├── services/                              # Runtime microservices — one FastAPI service per use case
│   ├── alert-correlator/
│   │   ├── src/correlator.py              # DBSCAN clustering with time-horizon scaling + one-hot namespace
│   │   ├── src/main.py                    # FastAPI: POST /correlate; returns cluster groups + FPR metric
│   │   └── Dockerfile                     # Non-root (uid 10001), python:3.11-slim
│   ├── anomaly-detector/
│   │   ├── src/main.py                    # LSTM autoencoder inference: POST /detect; reconstruction error score
│   │   └── Dockerfile
│   ├── cost-optimizer/
│   │   ├── src/main.py                    # IsolationForest cost anomaly: POST /analyze; anomaly flag + attribution
│   │   └── Dockerfile
│   ├── drift-monitor/
│   │   ├── src/drift_engine.py            # KS test + PSI + NannyML + Alibi drift detectors (composable)
│   │   ├── src/main.py                    # FastAPI: POST /detect-drift; returns per-detector scores + Evidently report
│   │   └── Dockerfile
│   ├── predictive-scaler/
│   │   ├── src/main.py                    # Linear trend forecaster (dependency-free) + shadow-mode evaluation
│   │   └── Dockerfile
│   ├── runbook-agent/
│   │   ├── runbooks/high-cpu-scaling.md   # Runbook: steps to diagnose and remediate high CPU spikes
│   │   ├── runbooks/pod-crashloop.md      # Runbook: CrashLoopBackOff diagnosis decision tree
│   │   ├── src/main.py                    # RAG: sanitize → embed → retrieve from Qdrant → ground → answer
│   │   └── Dockerfile
│   └── self-healing/
│       ├── src/main.py                    # POST /api/v1/remediate: OPA gate (fail-closed) + idempotency cache
│       ├── src/resilience.py              # retry_call (backoff+jitter) + CircuitBreaker primitives
│       └── Dockerfile                     # Non-root uid 10001, HEALTHCHECK, read-only-fs compatible
│
├── tests/
│   ├── unit/
│   │   ├── test_correlator.py             # 10 tests: DBSCAN clustering, FPR, dedup, edge cases
│   │   ├── test_drift_engine.py           # Drift engine unit tests: KS/PSI/NannyML detector correctness
│   │   ├── test_predictive_scaler.py      # Forecast accuracy + shadow-mode evaluation logic
│   │   ├── test_resilience.py             # 12 tests: retry backoff delays, circuit breaker state machine
│   │   ├── test_runbook_agent.py          # RAG hardening: sanitization, grounding, injection defense
│   │   ├── test_scorer.py                 # Eval framework: score computation, thresholds, edge cases
│   │   ├── test_self_healing.py           # Self-healing: OPA integration, idempotency, resilience
│   │   └── test_shadow_evaluator.py       # 8 tests: binary + forecast evaluators, promotion gate logic
│   ├── load/
│   │   ├── k6_self_healing.js             # k6: 100 VU ramp; asserts p95 < 500ms, no policy bypass under load
│   │   ├── k6_drift_monitor.js            # k6: sustained drift detection load + latency SLO assertion
│   │   └── k6_runbook_agent.js            # k6: RAG agent load including prompt-injection attempt payloads
│   ├── chaos/                             # Placeholder for future in-cluster chaos test harness
│   └── integration/                       # Placeholder for future end-to-end service integration tests
│
├── .pre-commit-config.yaml                # Hooks: ruff, black, hadolint (Dockerfiles), trailing whitespace
├── LICENSE                                # Apache 2.0
├── Makefile                               # Targets: test-unit, test-opa, lint, dev, ci-local, clean
├── pyproject.toml                         # ruff + black + pytest + mypy config; tool versions pinned
├── README.md                              # This document
├── renovate.json                          # Renovate bot: auto-PRs for dependency updates (weekly)
└── requirements.txt                       # Pinned Python deps: ML (scikit-learn, torch), MLOps (mlflow, evidently, feast), serving (fastapi, httpx)
```

---

## 6. Use cases (23)

Each UC has a numbered workflow, a blocking eval gate, and code under `services/` or `platform/`.

| UC | Capability | Algorithm / Tool (2026) | CI workflow | Pass threshold |
|----|-----------|------------------------|-------------|---------------|
| UC1 | ML data + prediction drift | KS test, PSI, NannyML, Alibi, Evidently | `03` | score ≥ 70 |
| UC2 | Log anomaly detection | LSTM autoencoder, PyTorch, Qdrant | `04` | score ≥ 65 |
| UC3 | Alert-storm correlation & de-duplication | DBSCAN (time-horizon scaled), silhouette | `06` | score ≥ 50 |
| UC4 | Predictive autoscaling | Linear trend forecast, KEDA, shadow mode | `07` | score ≥ 70 |
| UC5 | Feature train/serve skew detection | Feast, Great Expectations, Evidently | `05` | score ≥ 75 |
| UC6 | Agentic self-healing | OPA (fail-closed), Falco, n8n, retry+CB | `08` | score ≥ 85 |
| UC7 | Supply-chain & admission security | Trivy, Falco, Kyverno, SBOM/Cosign | `13`, `28` | score ≥ 75 |
| UC8 | RAG runbook Q&A | Qdrant, TinyLlama/Ollama, grounding | `09` | score ≥ 70 |
| UC9 | Safe model promotion | OPA `model_promotion.rego`, MLflow registry | `10` | score ≥ 80 |
| UC10 | Cloud cost anomaly + attribution | IsolationForest, MLflow | `11` | score ≥ 70 |
| UC11 | Distributed tracing RCA | OTEL Collector, Tempo, span correlation | `18` | score ≥ 65 |
| UC12 | GitOps compliance drift | Kyverno, OPA, `argocd diff` pattern | `19` | score ≥ 80 |
| UC13 | Data pipeline quality gates | Great Expectations, Airflow, OpenLineage | `20` | score ≥ 75 |
| UC14 | Hyperparameter optimization | Optuna, MLflow autolog, 20 trials | `21` | score ≥ 70 |
| UC15 | DORA metrics dashboard | GHA event API, Prometheus, Grafana | `14` | score ≥ 70 |
| UC16 | Intelligent error classification | sklearn, sentence-transformers | `22` | score ≥ 65 |
| UC17 | Model explainability + audit | SHAP, MLflow, EU AI Act checks | `23` | score ≥ 70 |
| UC18 | Predictive rate limiting | Redis, sklearn, sliding window | `24` | score ≥ 70 |
| UC19 | Feature monitoring / data profiling | WhyLogs, WhyLabs opt-in | `25` | score ≥ 65 |
| UC20 | Service catalog validation | Backstage, catalog-info.yaml schema | `26` | score ≥ 80 |
| UC21 | SLO / error-budget monitoring | Prometheus recording rules, burn-rate alerts | `15` | score ≥ 75 |
| UC22 | A/B testing + auto-promote | KServe traffic split, shadow evaluator | `10` | score ≥ 80 |
| UC23 | Auto post-mortem generation | RAG agent + Qdrant incident history | `09` | score ≥ 70 |

---

## 7. Key production patterns

**Fail-closed policy enforcement** (`services/self-healing/src/main.py` + `aiops/policies/opa/self_healing.rego`)
OPA is queried before every remediation. If OPA is unreachable — network partition, pod restart, timeout — the
service returns HTTP 503 and increments `self_healing_opa_unavailable_total`. It never defaults to allow.
Proven by `platform/chaos/opa-unavailable.yaml` which partitions the OPA network and asserts the verifier Job
sees only 503s during the fault window.

**Retry + circuit breaker + idempotency** (`services/self-healing/src/resilience.py`)
`retry_call` wraps the OPA HTTP call with exponential backoff + jitter (configurable via env vars).
`CircuitBreaker` trips after N consecutive failures and fast-fails until the reset window passes.
`_idempotency_cache` de-duplicates requests by content hash or an explicit `idempotency_key` so a retrying
caller cannot double-execute a live remediation.

**Shadow mode / online evaluation** (`platform/shadow-mode/shadow_evaluator.py`)
`BinaryShadowEvaluator` and `ForecastShadowEvaluator` score would-be decisions against ground truth and only
recommend promotion once every criterion (precision, recall, FPR, or MAE) clears its gate. The predictive
scaler ships in shadow mode by default — it forecasts but does not act until the evaluator promotes it.

**RAG hardening** (`services/runbook-agent/src/main.py`)
Four layers: (1) `_sanitize_question` strips prompt-injection markers and enforces a length ceiling;
(2) bounded `top_k` retrieval prevents context flooding; (3) deterministic unit-norm hash embeddings as a
dependency-free fallback; (4) `_groundedness` score checks that the answer tokens appear in the retrieved
context and refuses to surface ungrounded answers.

**Alert correlation** (`services/alert-correlator/src/correlator.py`)
DBSCAN with time scaled by a fixed 20-minute correlation horizon (not min-max across the whole window, which
chains all incidents together) and one-hot namespace encoding. FPR measures cross-incident contamination only —
a root alert correctly grouped with its own cascade alerts is not a false positive. Result: silhouette ≥ 0.87,
FPR ≤ 0.10 on the 24h synthetic dataset, composite score 99.8.

**Container + cluster hardening** (`services/*/Dockerfile`, `infra/kubernetes/base/self-healing/`)
All service images run as uid 10001 (non-root), expose no unnecessary ports, and include a `HEALTHCHECK`.
The Kubernetes base overlay adds: `readOnlyRootFilesystem`, all capabilities dropped (`ALL`), resource
requests/limits, liveness/readiness/startup probes, a `PodDisruptionBudget` (`minAvailable: 1`), and a
default-deny `NetworkPolicy` that whitelists only OPA egress and Prometheus/n8n ingress.

---

## 8. Quickstart

```bash
git clone https://github.com/sanjeev0120test/observable-mlops-platform.git
cd observable-mlops-platform

# Install Python tooling
pip install -r requirements.txt

# Run unit tests (101 tests, ~15s)
make test-unit            # or: python -m pytest tests/unit -q

# Lint exactly as CI does
make lint                 # ruff check . && black --check .

# OPA policy tests (requires opa binary)
make test-opa             # opa test aiops/policies/opa/ -v

# Bring up local observability stack (Docker Desktop required)
docker network create platform-net || true
docker compose -f infra/docker-compose/docker-compose.observability.yml -p platform-obs up -d
```

**Local endpoints** (when Docker stacks are running):

| Service | URL | Notes |
|---|---|---|
| Grafana | <http://localhost:3000> | `admin` / `admin` |
| Prometheus | <http://localhost:9090> | Targets at `/targets` |
| Alertmanager | <http://localhost:9093> | Routes UC6/UC23 webhooks |
| Loki | <http://localhost:3100> | Query via Grafana Explore |
| Tempo | <http://localhost:3200> | Traces via Grafana Explore |
| OTEL Collector | metrics: <http://localhost:8889> | OTLP gRPC on `4319` (host) → `4317` (container) |
| MLflow | <http://localhost:5000> | Stack A only |
| Airflow | <http://localhost:8080> | Stack A — retrain DAGs |
| Qdrant | <http://localhost:6333> | Stack A — RAG vector store |
| n8n | <http://localhost:5678> | Stack A — UC6/UC23 event automation |

---

## 9. CI reference

| Workflow | Purpose | Key gate |
|---|---|---|
| `00-pr-validate` | Lint (ruff, black), actionlint, OPA tests, structure | All must pass — blocks merge |
| `27-unit-tests` | 101 pytest unit tests + OPA policy tests | 0 failures |
| `29-resilience-chaos` | Chaos + k8s manifest validation + resilience/shadow/RAG tests | All valid |
| `28-sbom-signing` | Syft SBOM + Grype scan + Cosign signing + Trivy SARIF | Informational (SARIF to Security tab) |
| `90-e2e-integration` | Aggregate all UC scores; exit 1 if any UC fails | 100% UC pass rate |
| `91-publish-portal` | Deploy eval dashboard to GitHub Pages | Runs only after E2E success |
| `01` – `26` | Per-UC: generate data → run algorithm → log to MLflow → eval gate | Numeric threshold per UC |

Run all workflows locally with `make ci-local` (lint + unit tests + data generators).

---

## 10. Security & governance

| Layer | What | Where |
|---|---|---|
| **Policy-as-code** | OPA (remediation + model promotion) + Kyverno (admission) | `aiops/policies/` |
| **Runtime security** | Falco rules: crypto miner, shell-in-container, privilege escalation | `aiops/falco/custom_rules.yml` |
| **Supply chain** | Trivy image scan + Syft SBOM + Cosign keyless signing | `.github/workflows/28-sbom-signing.yml` |
| **Least privilege** | Non-root containers, dropped capabilities, read-only root filesystem | `services/*/Dockerfile`, `infra/kubernetes/` |
| **Network isolation** | Default-deny NetworkPolicy; explicit allow-lists per service | `infra/kubernetes/base/self-healing/networkpolicy.yaml` |
| **Compliance** | EU AI Act: model card presence, bias metric logging, audit trail | `governance/eu-ai-act/compliance_check.py` |
| **Dependency hygiene** | Renovate bot auto-PRs for outdated deps weekly | `renovate.json` |

---

## 11. Local Observability Lab — Runbook & Lessons Learned

**Last validated locally:** 2026-06-11 (Docker Desktop on Windows; Stack B + metrics hub + OTEL seed).

**Purpose:** Run Prometheus, Grafana, Loki, Tempo, and OTEL locally with **real data in every UI** — not just empty
infrastructure. Documents every setup failure encountered and the exact fix applied.

> **CI vs local:** GitHub Actions runs **Stack B only** in `01-observability.yml` (health checks + alert rule
> inventory). Full dashboard data requires application metrics from Stack C microservices or the metrics hub
> workaround below. MLflow/DVC run in CI via DagsHub; locally MLflow is on `:5000` when Stack A is up.

### Quick links

| Resource | URL |
|---|---|
| GitHub repo | <https://github.com/sanjeev0120test/observable-mlops-platform> |
| All GitHub Actions | <https://github.com/sanjeev0120test/observable-mlops-platform/actions> |
| DVC + MLflow remote (DagsHub) | <https://dagshub.com/sanjeev0120test/observable-mlops-platform> |
| Eval portal (GitHub Pages) | <https://sanjeev0120test.github.io/observable-mlops-platform/> |

### Prerequisites

| Requirement | Notes |
|---|---|
| Docker Desktop | ~8 GB RAM for Stack A+B together; Stack B alone ~1.8 GB |
| Git clone | `git clone https://github.com/sanjeev0120test/observable-mlops-platform.git` |
| Python 3.11+ | For OTEL seed scripts and Grafana API datasource fix |
| `DAGSHUB_TOKEN` | GitHub Secret — required for CI MLflow/DVC logging; not needed for local Docker runs |

### Step-by-step: end-to-end local demo

```mermaid
flowchart TD
    A[1. Create platform-net] --> B[2. Start Stack B + Prometheus override]
    B --> C[3. Start Stack A optional]
    C --> D[4. Metrics hub OR Stack C services]
    D --> E[5. Fix Grafana datasource binding]
    E --> F[6. Seed OTEL traces and logs]
    F --> G[7. Validate all UIs]
    G --> H[8. Cleanup]
```

#### Step 1 — Shared Docker network

```bash
docker network create platform-net || true
```

#### Step 2 — Start Stack B (observability)

```bash
docker compose -f infra/docker-compose/docker-compose.observability.yml -p platform-obs up -d
# Wait ~60s then verify:
curl -sf http://localhost:9090/-/healthy && echo "Prometheus OK"
curl -sf http://localhost:3000/api/health && echo "Grafana OK"
curl -sf http://localhost:3100/ready && echo "Loki OK"
curl -sf http://localhost:3200/ready && echo "Tempo OK"
```

Enable Prometheus remote-write receiver (required for OTEL metrics):

```yaml
# docker-compose.observability.override.yml
services:
  prometheus:
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=7d"
      - "--web.enable-lifecycle"
      - "--web.enable-remote-write-receiver"
```

```bash
docker compose -f infra/docker-compose/docker-compose.observability.yml \
  -f docker-compose.observability.override.yml -p platform-obs up -d --force-recreate prometheus
```

#### Step 3 — Stack A (MLflow, Postgres, Redis, Qdrant, n8n) — optional

```bash
# Override to join the shared network if Stack B was started first
# docker-compose.mlops-core.override.yml:
#   networks:
#     default:
#       name: platform-net
#       external: true

docker compose -f infra/docker-compose/docker-compose.mlops-core.yml \
  -f docker-compose.mlops-core.override.yml -p platform-ml up -d \
  postgresql redis mlflow qdrant n8n
```

#### Step 4 — Application metrics (metrics hub workaround)

Prometheus scrapes Stack C hostnames (`anomaly-detector`, `drift-monitor`, …). A lightweight Python container
with network aliases satisfies the scrape targets without requiring every service to build:

```bash
docker rm -f platform-metrics-hub 2>/dev/null
docker run -d --name platform-metrics-hub --network platform-net \
  --network-alias anomaly-detector --network-alias drift-monitor \
  --network-alias alert-correlator --network-alias predictive-scaler \
  --network-alias self-healing --network-alias runbook-agent \
  --network-alias cost-optimizer \
  -v "$(pwd)/metrics-hub.py:/app/hub.py:ro" \
  python:3.11-slim bash -c "pip install -q prometheus_client && python /app/hub.py"
```

Verify targets: <http://localhost:9090/targets> — all `platform-services` targets should be **UP**.

#### Step 5 — Fix Grafana datasource binding

File-provisioned dashboards use `"uid": "${DS_PROMETHEUS}"`. Grafana does not resolve this template at
provision time, so panels show **No data** even when Prometheus has metrics. Fix via API:

```python
# python fix-grafana-dashboard.py
import base64, json, urllib.request
auth = base64.b64encode(b"admin:admin").decode()
hdrs = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
with urllib.request.urlopen(urllib.request.Request(
    "http://localhost:3000/api/datasources", headers=hdrs)) as r:
    prom_uid = next(d["uid"] for d in json.load(r) if d["type"] == "prometheus")
# Then GET the dashboard, replace ${DS_PROMETHEUS} → prom_uid, POST back
```

#### Step 6 — Seed OTEL traces and logs

```bash
python scripts/setup-ollama.sh   # optional: pulls TinyLlama for runbook agent
# Send a test trace to OTEL collector:
curl -X POST http://localhost:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[]}'
```

#### Step 7 — Validate all UIs

| UI | URL | What to verify |
|---|---|---|
| Grafana Platform Overview | <http://localhost:3000/d/platform-overview> | All panels populated, no "No data" |
| Prometheus Targets | <http://localhost:9090/targets> | All `platform-services` UP |
| Prometheus Alerts | <http://localhost:9090/alerts> | `MLModelDriftDetected` firing (UC1) |
| Alertmanager | <http://localhost:9093> | Drift alerts routed and grouped |
| OTEL Collector | <http://localhost:8889/metrics> | `otelcol_receiver_accepted_*` > 0 |
| Qdrant | <http://localhost:6333> | Dashboard reachable (Stack A) |
| MLflow | <http://localhost:5000> | Experiments visible (Stack A) |

#### Step 8 — Cleanup

```bash
docker compose -p platform-obs down -v
docker compose -p platform-ml down -v
docker rm -f platform-metrics-hub
docker network rm platform-net
```

### Visual walkthrough (51 screenshots)

Evidence from the **2026-06-11** local validation session and **CI runs on DagsHub/GitHub Actions**. Every screenshot is stored in [`docs/images/local-observability-lab/`](docs/images/local-observability-lab/) and referenced below in runbook order.

#### A. Docker Desktop — images, volumes, and Grafana bind mounts (7)

| # | Screenshot | What it proves |
|---|---|---|
| 01 | ![Docker Desktop local images](docs/images/local-observability-lab/01.png) | Observability images pulled (Prometheus, Grafana, Loki, Tempo, OTEL, Alertmanager, Fluent Bit). |
| 02 | ![Docker volumes list](docs/images/local-observability-lab/02.png) | Stack B persistent volumes (`platform-obs_*`) created and in use. |
| 03 | ![Grafana volume stored data](docs/images/local-observability-lab/03.png) | Grafana state persisted in `grafana.db` inside `platform-obs_grafana_data`. |
| 04 | ![Prometheus volume WAL](docs/images/local-observability-lab/04.png) | Prometheus TSDB writing WAL/chunks (metrics actively ingested). |
| 05 | ![Loki volume stored data](docs/images/local-observability-lab/05.png) | Loki chunks + tsdb-shipper directories present on disk. |
| 06 | ![Tempo volume stored data](docs/images/local-observability-lab/06.png) | Tempo trace blocks/WAL written to `platform-obs_tempo_data`. |
| 07 | ![Grafana container bind mounts](docs/images/local-observability-lab/07.png) | Dashboard + datasource provisioning paths mounted from repo into Grafana. |

#### B. Grafana — Platform Overview dashboard (2)

| # | Screenshot | What it proves |
|---|---|---|
| 08 | ![Grafana overview health PSI alerts](docs/images/local-observability-lab/08.png) | **After datasource fix**: Platform Health 100%, Active Alerts (7), Model PSI (UC1) panels populated. |
| 09 | ![Grafana overview SLO cost](docs/images/local-observability-lab/09.png) | HTTP Error Rate SLO (UC21) and Cost by Namespace (UC10) panels show live series. |

#### C. Grafana Explore — Prometheus queries (4)

| # | Screenshot | What it proves |
|---|---|---|
| 10 | ![Explore ml_model_psi_score graph](docs/images/local-observability-lab/10.png) | `ml_model_psi_score` time series from metrics hub / platform-services job. |
| 11 | ![Explore ml_model_psi_score raw table](docs/images/local-observability-lab/11.png) | 14 PSI series across all seven service hostnames on `:8000`. |
| 12 | ![Explore platform_seed_active_requests](docs/images/local-observability-lab/12.png) | OTEL-seeded gauge visible in Prometheus via Grafana Explore. |
| 13 | ![Explore metric picker ml_model_psi_score](docs/images/local-observability-lab/13.png) | Metric autocomplete confirms Prometheus datasource bound correctly. |

#### D. Prometheus — targets, rules, alerts (10)

| # | Screenshot | What it proves |
|---|---|---|
| 14 | ![Prometheus targets 7 of 7 up](docs/images/local-observability-lab/14.png) | All `platform-services` scrape targets **UP** (metrics hub aliases working). |
| 15 | ![Prometheus target detail cost-optimizer](docs/images/local-observability-lab/15.png) | Individual target labels, 30s scrape interval, endpoint `/metrics`. |
| 16 | ![Prometheus SLO recording rules](docs/images/local-observability-lab/16.png) | `job:http_error_rate:ratio5m` + `SLOFastBurnRate` rules loaded (UC21). |
| 17 | ![Prometheus UC2 UC4 alert rules](docs/images/local-observability-lab/17.png) | `HighCPUPreScale` (UC4) and `PodCrashLoopBackOff` (UC2) rules present. |
| 18 | ![Prometheus graph ml_model_psi_score](docs/images/local-observability-lab/18.png) | PSI query returns series for `pod-failure-prediction` across instances. |
| 19 | ![Prometheus service discovery](docs/images/local-observability-lab/19.png) | `otel-collector` and `platform-services` jobs discovered on `platform-net`. |
| 20 | ![Prometheus TSDB label stats](docs/images/local-observability-lab/20.png) | TSDB label cardinality — confirms active metric ingestion. |
| 21 | ![Prometheus TSDB series counts](docs/images/local-observability-lab/21.png) | Top series by metric name (HTTP histogram buckets, app metrics). |
| 22 | ![Prometheus alerts MLModelDriftDetected firing](docs/images/local-observability-lab/22.png) | **UC1 drift alert firing** (7 instances) when PSI ≥ 0.2. |
| 23 | ![Prometheus alert rule detail UC1](docs/images/local-observability-lab/23.png) | `MLModelDriftDetected` expression and firing instance breakdown. |

#### E. Alertmanager (2)

| # | Screenshot | What it proves |
|---|---|---|
| 24 | ![Alertmanager grouped drift alerts](docs/images/local-observability-lab/24.png) | Prometheus alerts routed to Alertmanager (UC1 drift group). |
| 25 | ![Alertmanager cluster status](docs/images/local-observability-lab/25.png) | Alertmanager healthy, single-peer cluster ready. |

#### F. OTEL Collector and Qdrant (2)

| # | Screenshot | What it proves |
|---|---|---|
| 26 | ![OTEL collector metrics endpoint](docs/images/local-observability-lab/26.png) | `localhost:8889/metrics` — OTEL accepted logs/spans/metrics, zero refused. |
| 27 | ![Qdrant dashboard console](docs/images/local-observability-lab/27.png) | Stack A Qdrant UI reachable on `:6333` (RAG/UC8 vector store). |

#### G. GitHub Actions — CI validation (7)

| # | Screenshot | What it proves |
|---|---|---|
| 28 | ![GitHub Actions UC1 drift workflow](docs/images/local-observability-lab/28.png) | `03-drift-detection.yml` green — UC1 eval gate passed in CI. |
| 29 | ![GitHub Actions publish portal](docs/images/local-observability-lab/29.png) | `91-publish-portal.yml` deploys eval dashboard to GitHub Pages. |
| 30 | ![GitHub Actions E2E workflow YAML](docs/images/local-observability-lab/30.png) | `90-e2e-integration.yml` aggregates all 23 UC workflow results. |
| 31 | ![GitHub Pages deployment](docs/images/local-observability-lab/31.png) | Pages build/deploy job succeeded (`gh-pages` branch). |
| 32 | ![GitHub Actions all workflows list](docs/images/local-observability-lab/32.png) | Recent runs green across observability, E2E, portal, and UC workflows. |
| 33 | ![GitHub Actions 01-observability history](docs/images/local-observability-lab/33.png) | Stack B workflow history — failed run then **fix commit** (`fa64bf8`) green. |
| 34 | ![GitHub Actions observability health steps](docs/images/local-observability-lab/34.png) | CI validates datasources, OTEL span, Prometheus rules, UC alert coverage. |

#### H. DagsHub — experiments and model registry (5)

| # | Screenshot | What it proves |
|---|---|---|
| 35 | ![DagsHub experiments tab](docs/images/local-observability-lab/35.png) | 16 MLflow runs on DagsHub with drift/HPO/SHAP metrics (UC1, UC14, UC17). |
| 36 | ![DagsHub registered models](docs/images/local-observability-lab/36.png) | Model registry: `cost-anomaly-detector` v1, `pod-failure-prediction` v3. |
| 37 | ![DagsHub cost model charts](docs/images/local-observability-lab/37.png) | UC10 cost model f1/precision/recall charts on DagsHub. |
| 38 | ![DagsHub pod-failure model versions](docs/images/local-observability-lab/38.png) | Pod-failure-prediction versions 1–3 with linked source runs. |
| 39 | ![DagsHub isolation-forest run detail](docs/images/local-observability-lab/39.png) | Finished `isolation-forest-ci` run with UC10 tags and metrics. |

#### I. MLflow on DagsHub — per-UC run evidence (12)

| # | Screenshot | What it proves |
|---|---|---|
| 40 | ![MLflow isolation-forest overview](docs/images/local-observability-lab/40.png) | UC10 run: f1 0.896, precision 0.867, recall 0.926, sklearn logged. |
| 41 | ![MLflow home experiments list](docs/images/local-observability-lab/41.png) | Five experiments: explainability, pod-failure, HPO, cost, alert-correlation. |
| 42 | ![MLflow UC17 SHAP metrics](docs/images/local-observability-lab/42.png) | UC17 `uc17-shap-ci`: `n_explained_predictions` = 200. |
| 43 | ![MLflow pod-failure runs table](docs/images/local-observability-lab/43.png) | UC9 candidate/baseline GBC runs linked to model versions v1–v3. |
| 44 | ![MLflow candidate-gbc overview](docs/images/local-observability-lab/44.png) | UC9 candidate run registered as `pod-failure-prediction` v3. |
| 45 | ![MLflow baseline-gbc overview](docs/images/local-observability-lab/45.png) | UC9 baseline run with GBC hyperparameters and UC9 baseline tag. |
| 46 | ![MLflow Optuna HPO overview](docs/images/local-observability-lab/46.png) | UC14 `optuna-study-ci`: 20 trials, best f1 logged to MLflow. |
| 47 | ![MLflow alert-correlation runs](docs/images/local-observability-lab/47.png) | UC1 + UC3 drift/DBSCAN runs in `alert-correlation` experiment. |
| 48 | ![MLflow UC1 drift overview](docs/images/local-observability-lab/48.png) | UC1 `uc1-drift-detection-ci`: PSI, KS, NannyML, Alibi metrics; drift detected. |
| 49 | ![MLflow UC1 drift model metrics charts](docs/images/local-observability-lab/49.png) | UC1 drift metric charts (ks_statistic 0.32, psi_score, etc.). |
| 50 | ![MLflow UC3 DBSCAN overview](docs/images/local-observability-lab/50.png) | UC3 `uc3-dbscan-ci`: deduplication_rate, silhouette_score, false_positive_rate. |
| 51 | ![MLflow UC3 DBSCAN model metrics](docs/images/local-observability-lab/51.png) | UC3 metric charts: deduplication_rate 0.88, false_positive_rate 0.96. |

> **Tip**: Start with **A–F** for local observability proof, then **G** for CI evidence, then **H–I** for MLflow/DVC lineage on DagsHub.

### Recommended permanent repo improvements (not yet applied)

These would remove the need for local override files and API patches:

1. Add `--web.enable-remote-write-receiver` to [`docker-compose.observability.yml`](infra/docker-compose/docker-compose.observability.yml) Prometheus command
2. Fix `${DS_PROMETHEUS}` in [`overview.json`](observability/dashboards/grafana/overview.json) to use the provisioned datasource UID from `grafana-provisioning/datasources/`
3. Set `external: true` on `platform-net` in [`docker-compose.mlops-core.yml`](infra/docker-compose/docker-compose.mlops-core.yml) (match Stack B/C)
4. Fix Stack C Dockerfiles (torch pip index URL, OPA image tag) so the metrics hub workaround is not required
5. Add `scripts/local/` with metrics-hub, telemetry-seed, and Grafana-fix scripts checked into git

---

## 12. Enterprise production context

### How this platform maps to real org patterns at scale

The table below cross-references each use case against publicly documented patterns from hyperscalers and CNCF projects. This is how mature SaaS engineering orgs actually use these tools.

| Enterprise pattern | What they publish / do | Problem solved | This repo's UC(s) | Public reference |
|---|---|---|---|---|
| **Google SRE — SLO + error budget** | Multi-window burn alerts; error budget policy gates releases | SLO breaches discovered too late; releases during outage windows | UC21 | [Google SRE Book — SLOs](https://sre.google/sre-book/service-level-objectives/), [Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/) |
| **DORA Four Keys** | Deployment frequency, lead time, CFR, MTTR as engineering health KPIs | No visibility into delivery pipeline health | UC15 | [dora.dev](https://dora.dev/), [2023 State of DevOps](https://cloud.google.com/devops/state-of-devops) |
| **Spotify — Backstage** | Service catalog, ownership, API discovery in one internal portal | Engineers don't know who owns what during incidents | UC20 | [Backstage.io](https://backstage.io/docs/overview/what-is-backstage/) |
| **Uber — Michelangelo** | Central ML platform with shared feature pipelines for train/serve | Training-serving skew; siloed ML teams reimplementing the same infra | UC5, UC9 | [Uber Engineering — Michelangelo](https://www.uber.com/blog/michelangelo-machine-learning-platform/) |
| **Netflix — ML observability** | Continuous model monitoring; automated remediation culture | Silent model degradation; manual ops that don't scale past hundreds of models | UC1, UC6 | [Netflix TechBlog](https://netflixtechblog.com/) |
| **LinkedIn — data quality at scale** | Expectations on data pipelines before downstream ML jobs | Bad data poisoning models silently; no audit trail | UC13 | [LinkedIn Engineering](https://engineering.linkedin.com/) |
| **Airbnb — Great Expectations origin** | Declarative data tests embedded in pipelines | Schema drift, null spikes, type changes in production data | UC5, UC13 | [Great Expectations docs](https://docs.greatexpectations.io/) |
| **CNCF — OTEL + Prometheus + Grafana** | Vendor-neutral telemetry; single collector fan-out to multiple backends | Tool sprawl; no correlated traces/logs/metrics in one place | UC11, all obs | [OTEL](https://opentelemetry.io/), [Prometheus](https://prometheus.io/) |
| **CNCF — OPA / Kyverno admission** | Policy-as-code enforced at deploy time and runtime | CVE-bearing images; non-compliant manifests reaching production | UC7, UC12 | [OPA](https://www.openpolicyagent.org/docs/latest/), [Kyverno](https://kyverno.io/) |
| **KServe / Knative — canary serving** | InferenceService canary splits, scale-to-zero, shadow mode | Risky big-bang model rollouts; serving infra cost during quiet hours | UC9, UC22 | [KServe canary rollout](https://kserve.github.io/website/latest/modelserving/v1beta1/rollout-strategy/) |
| **Shopify — production ML monitoring** | Drift and feature distribution monitoring in live commerce | Revenue-impacting prediction degradation caught days after deployment | UC1, UC19 | [Shopify Engineering](https://shopify.engineering/) |

### Real production scenarios — platform response

Representative incident classes from SaaS post-mortems. Each row shows how this repo's CI-proven UC chain would detect and respond.

| Scenario | Symptoms in prod | Business impact | Platform response (UC chain) | CI evidence |
|---|---|---|---|---|
| **Payment fraud model drift** | Approval rate shifts; chargebacks spike days later | Wrong fraud decisions; regulatory scrutiny | UC1 PSI/KS → Airflow retrain; UC19 WhyLogs early warning | `03`, `25` |
| **Black Friday CPU spike** | p99 latency spikes; HPA lags behind load | Cart/checkout degradation; SLO burn | UC4 forecast → KEDA pre-scale; UC21 fast-burn alert fires | `07`, `15` |
| **Log storm after bad deploy** | ERROR volume floods dashboards; root cause buried | Long MTTR; alert fatigue; wrong escalations | UC2 LSTM anomaly; UC3 DBSCAN dedup; UC8 RAG runbook answer | `04`, `06`, `09` |
| **CVE in base Python image** | Trivy flags CRITICAL in CI build | Compliance audit fail; exploit risk | UC7 blocks promotion; Kyverno denies admission | `13`, `28` |
| **Feature skew after refactor** | Model accuracy drops post-deploy; features "look fine" in isolation | Silent wrong predictions in production | UC5 Feast offline vs online PSI check | `05` |
| **On-call restart of wrong namespace** | Engineer restarts kube-system pod at 3am | Cluster instability; cascading failure | UC6 OPA allows `payments`; denies `kube-system` — HTTP 403 | `08` |
| **Model promoted without explainability** | Regulator asks for prediction rationale post-incident | Audit block; potential fine | UC17 SHAP → MLflow; OPA `model_promotion.rego` denies promotion if SHAP run absent | `23`, `10` |
| **Idle GPU namespaces** | Utilization near zero on dev/test clusters for weeks | Unnecessary cloud spend; budget overrun | UC10 IsolationForest waste ratio → Prometheus alert | `11` |
| **429 storm on public API** | Reactive rate limits block legitimate users | SLA miss; support tickets; revenue impact | UC18 predictive Redis limits from traffic forecast | `24` |
| **Post-mortem takes 4 hours** | Engineer searches Confluence + Slack manually for similar incidents | Slow learning loop; same incidents repeat | UC23 RAG → n8n → draft GitHub Issue with linked runbook | `09` |

### How enterprises adopt this incrementally

Large organizations do not deploy all 23 use cases on day one. The realistic adoption path:

**Phase 1 — Baseline observability (weeks 1–4)**
Set up Prometheus + Grafana + Alertmanager + OTEL. Define SLOs (UC21). This alone
reduces on-call noise by routing only budget-burning alerts. Most orgs already have
Datadog/New Relic here — OTEL is the migration path out of vendor lock-in.

**Phase 2 — ML monitoring (weeks 4–12)**
Add drift detection (UC1) and anomaly detection (UC2). Wire to Airflow retrain DAG.
This is where most orgs first measure real model ROI: they discover their "98% accurate"
model was actually at 71% for two months before anyone noticed.

**Phase 3 — Policy and governance (weeks 8–16)**
Add OPA policy gates (UC6, UC9) and Kyverno admission. This unblocks compliance teams
who were manually reviewing every production change. The key insight: policy as code
means audit evidence is automatic, not a quarterly scramble.

**Phase 4 — Intelligent operations (weeks 12–24)**
Add alert correlation (UC3), self-healing (UC6), and RAG runbooks (UC8/UC23). At this
stage teams reduce P1 incident MTTR from 45+ minutes to under 10 because the system
can narrow root cause and surface the exact runbook before a human starts Slack threads.

**Phase 5 — Full ML lifecycle (ongoing)**
HPO (UC14), explainability (UC17), feature monitoring (UC19), DORA metrics (UC15),
SBOM signing (UC7). These are the patterns that separate a team that ships ML from one
that can defend their ML to auditors, regulators, and the board.

### Eval scoring — how the CI gate works

Every UC workflow writes structured metrics to `eval-results/ucN_metrics.json`. `run_eval_gate` in `eval/scorer.py` computes:

```
composite_score = sum(score_i * weight_i for each metric_i) / total_weight
```

Where each `score_i` is 0–100:
- `higher_better`: `min(100, (observed / threshold) * 100)`
- `lower_better`: `min(100, max(0, (1 - (observed - threshold) / threshold) * 100))`
- `bool_true`: `100 if observed else 0`

If `composite_score < THRESHOLDS[UC]`, the job calls `sys.exit(1)` — the CI job fails, the PR is blocked, and `90-e2e-integration` cannot aggregate. The threshold is the contract; the CI run is the proof.

```python
# eval/metrics.py — UC3 example
UC_METRICS["UC3"] = [
    MetricSpec("deduplication_rate", "higher_better", pass_threshold=0.70, weight=2.0),
    MetricSpec("silhouette_score",   "higher_better", pass_threshold=0.30, weight=1.5),
    MetricSpec("false_positive_rate","lower_better",  pass_threshold=0.10, weight=2.0),
]
THRESHOLDS["UC3"] = 50  # composite must reach 50/100
```

---

## License

[Apache 2.0](LICENSE)
