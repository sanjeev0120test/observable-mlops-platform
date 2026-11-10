# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [0.5.0] - 2026-11-10

### Upgrade notes
- **Postgres 18 needs a fresh volume.** The data directory layout changed, so the
  `postgres_data` volume now mounts at `/var/lib/postgresql`. Run
  `docker compose -p mlops-platform down -v` (or dump/restore) before `make dev`.
- Airflow 3.4: the webserver is replaced by `airflow-apiserver` (port 8080) plus a
  separate `airflow-dag-processor`; REST calls use `/auth/token` + `/api/v2`.
  Set `AIRFLOW__API_AUTH__JWT_SECRET` in `.env` for any shared deployment (the compose
  default is a lab-only value).
- `requirements.txt` is gone: install with `make install` (uv, `uv.lock`).

### Changed
- Python 3.14 everywhere (services, CI, devcontainer); dependencies moved to PEP 735
  groups in `pyproject.toml` with a single `uv.lock`, so each CI job installs only its
  group (torch and prophet only for the UCs that train with them; langchain, nannyml
  and alibi-detect are dropped). Service images install with uv.
- Stack images: Postgres 18.6, Redis 8.8, MLflow 3.18, Airflow 3.4, n8n 2.47,
  Qdrant 1.20, Ollama 0.40, Prometheus 3.16, Alertmanager 0.34, Grafana 13.3,
  Loki 3.7, Tempo 2.10, OTel Collector 0.165, Fluent Bit 5.1, OPA 1.22.
- Kyverno policies are `ValidatingPolicy` (CEL) with CLI tests; UC7 runs Kyverno 1.19,
  Trivy 0.76 (cached DB) and validates the Falco rules with Falco 0.45.
- UC5 measures skew against a real Feast 0.67 Redis online store (materialize →
  `get_online_features` vs latest offline rows). Fixed the Redis connection string
  (Feast expects `host:port,db=0`) and the synthetic timestamps (now real datetimes).
- UC19 uses Evidently tests (with a clean-data negative control) instead of whylogs;
  UC13/UC5/UC2 data checks use Great Expectations 1.x via `eval/data_quality.py`.
- UC8 uses the qdrant-client 1.20 `query_points` API.

### CI
- One PR gate, `ci.yml`, replaces `00`, `27`, `29`, `30` and `gitleaks.yml`: path-filtered
  jobs, uv-cached Python setup, pytest-xdist, container smoke tests with the GitHub
  Actions layer cache, observability config validation in the real images, and a single
  required check `ci-ok`.
- `uc-evals.yml` calls the 23 UC gates as reusable workflows (changed UCs on merge, all
  nightly) and replaces the `workflow_run` cascade in `90`/`91`.
- `auto-merge.yml` reacts to `ci` completion (hourly sweep as a fallback) instead of
  polling every five minutes, and uses native auto-merge once `ci-ok` is a required
  check.
- `security.yml` replaces `28-sbom-signing.yml` and `sbom.yml`; Dependabot covers
  actions, uv, Docker, Compose and Terraform and replaces Renovate.
- Ruff format replaces Black.

### Fixed
- Upload paths with `{a,b}` braces matched nothing, so UC8/UC23 and UC9/UC17 results
  never reached the aggregate.
- The drift monitor container failed to import `drift_engine`; the UC1 retrain step
  wrote to a literal `$GITHUB_OUTPUT` file; the aggregator crashed on `*_metrics.json`.

## [0.4.0] - 2026-10-17

### Added
- `POST /api/v1/score/from-evidence` assembles Model Trust signals from MLflow metrics
  and tags, a Trivy report, a Kyverno policy report, and an EU AI Act compliance
  report. A source that did not run is left unobserved rather than scored as clean.
  The retrain DAG sends that evidence bundle instead of a hand-built signal dict.
- The retrain DAG runs the EU AI Act checker (mounted into the Airflow workers)
  and attaches `to_trust_evidence()` to that bundle, so a real compliance failure
  applies the PRIME cap. A model card for `pod-failure-prediction` documents the
  remaining SHAP gap.
- `scripts/promotion_rehearsal.py` runs three candidates through the real checker,
  the evidence assembler, the ledger (including a tamper check), and the OPA
  promotion policy using each candidate's own accuracy, drift, and SHAP flag.
  Workflow 30 runs it with `--require-opa`.
- Model Trust serves an operator console at `GET /` (also `http://localhost:8008`
  in Compose) that scores a version from evidence and shows the ledger.
- A recorded rescore that falls a band or at least 50 points sets `regression` on
  the score response, increments `model_trust_regressions_total`, and fires
  `ModelTrustRegression`.

## [0.3.0] - 2026-10-17

### Added
- **Model Trust Score** (`services/model-trust/`): FICO-style 300–1000 score per model version
  from six pillars (performance, drift, reliability, security, governance, cost), with knockout
  caps (critical CVEs, unsigned image, policy violations, exhausted error budget, EU AI Act
  non-compliance), a remediation advisor ranked by points-recovered-per-hour, and a SHA-256
  hash-chained append-only ledger with `/verify` and `/attestation` endpoints. 29 unit tests.
- OPA `model_promotion` now accepts `input.trust`: production requires ≥ 700, SUBPRIME (< 600)
  is denied everywhere, a failed ledger integrity check denies everything. 6 new Rego tests
  (36 total). Backward compatible when `trust` is absent.
- Airflow retrain DAG: new `compute_trust_score` task between training and the OPA gate; the
  score is passed into the gate. Fail-open on scorer outage (OPA remains fail-closed).
- Prometheus alerts `ModelTrustSubprime`, `ModelTrustDegradedBelowProductionBar`,
  `ModelTrustLedgerIntegrityFailed`; three Grafana overview panels.
- Workflow `30-model-trust-score`: engine tests → 3-model demo with tamper proof and OPA
  decisions (job summary + attestation artifact) → container smoke test (non-root, read-only
  rootfs, HTTP scoring).
- Kubernetes base for `model-trust` (PVC-backed ledger, default-deny NetworkPolicy, hardened
  pod security) and Compose service on port 8008 (`make trust-demo`, `make trust-score`).
- Terraform AWS EKS footprint (`infra/terraform/aws-eks/`): 3-AZ VPC with flow logs, EKS with
  IRSA + Pod Identity + KMS-encrypted secrets + full control-plane logging, on-demand platform
  pool and spot inference pool (IMDSv2, encrypted gp3), S3 MLflow/DVC bucket (versioned,
  SSE-KMS, public access blocked, lifecycle), scoped IRSA role for MLflow. `terraform fmt` and
  `validate` run in workflow 13.
- Backstage catalog: `model-trust` component + `model-trust-api` API entity.

### Changed
- **MLflow 2.13 → 3.17.1** across all workflows and service images. `log_model` calls migrated
  to the MLflow 3 API (`name=` instead of positional `artifact_path`) and pass
  `skops_trusted_types=["sklearn.tree._tree.Tree"]`: MLflow 3 serialises sklearn models with the
  pickle-free skops format, which refuses tree ensembles (GradientBoosting, IsolationForest)
  unless the node type is explicitly trusted. The Compose MLflow server is now built from
  `infra/docker-compose/mlflow/Dockerfile` (adds the Postgres driver and boto3 the upstream
  image omits, runs non-root). Model Trust writes `trust_score` / `trust_band` tags to the
  MLflow 3 model version.
- `28-sbom-signing` Trivy matrix now covers `predictive-scaler` and `model-trust` (was missing
  one existing service).

## [0.2.0] - 2026-10-17

### Fixed
- `00 · PR Validate` was red on `main`: unpinned Ruff/Black drifted and flagged
  `scripts/audit_readme.py`. Lint tools are now pinned (Ruff 0.17.1, Black 26.10.1) in CI,
  pre-commit, and `pyproject.toml`.
- `pyproject.toml` declared a non-existent build backend (`setuptools.backends.legacy:build`);
  `pip install .` now works (`setuptools.build_meta`).
- `make dev` failed: `docker-compose.services.yml` has `depends_on` targets defined in the core
  and observability files, but they were started as separate projects. The Makefile now runs a
  single merged Compose project (and starts the observability stack it advertises).
- OPA container healthcheck called `curl`, which the distroless image lacks, so `self-healing`
  (which waits on `service_healthy`) never started.
- Service container healthchecks called `curl`, which `python:3.11-slim` lacks; they now use
  Python's `urllib`.
- `anomaly-detector` image could not build: `--index-url` forced every package to resolve from
  the PyTorch CPU index. Switched to `--extra-index-url`.
- `.env.example` was git-ignored (matched `.env.*`), so fresh clones could not run `make dev`.
- `make seed-qdrant` and `make kind-up` referenced files that do not exist.

### Changed
- OPA 0.65 → 1.21.2 everywhere (CI, Makefile, Compose). Rego policies and tests migrated to
  Rego v1 syntax (`opa fmt --v0-v1`); all 30 policy tests pass.
- GitHub Actions upgraded to current majors: checkout v7, setup-python v7, upload-artifact v7,
  download-artifact v8, codeql-action v4, actionlint 1.7.12, sbom-action v0.24.3,
  scan-action v7. `trivy-action@master` pinned to `v0.36.0`.
- Unit tests run on a Python 3.11 + 3.12 matrix.
- `setup-kind.sh` defaults: kubectl 1.37.1, Helm 3.22.1; downloads fail fast on HTTP errors.

### Security
- Every workflow now declares a least-privilege `GITHUB_TOKEN` (`contents: read` unless a job
  explicitly needs more).
- All seven service images run as non-root (uid 10001) with a container `HEALTHCHECK`.
- Pre-commit adds gitleaks secret scanning.
- Added `SECURITY.md`, `CONTRIBUTING.md`, `CODEOWNERS`, PR template, and `.gitattributes`
  (LF line endings).

## [0.1.0]

Initial platform: 23 AIOps/MLOps use cases, CI-gated with eval scoring.
