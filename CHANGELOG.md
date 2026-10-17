# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

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
