# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased]

### Added
- `POST /api/v1/score/from-evidence` assembles Model Trust signals from MLflow metrics
  and tags, a Trivy report, a Kyverno policy report, and an EU AI Act compliance
  report. A source that did not run is left unobserved rather than scored as clean.
  The retrain DAG sends that evidence bundle instead of a hand-built signal dict.
- The retrain DAG runs the EU AI Act checker (mounted into the Airflow workers)
  and attaches `to_trust_evidence()` to that bundle, so a real compliance failure
  applies the PRIME cap. A model card for `pod-failure-prediction` documents the
  remaining SHAP gap.

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
