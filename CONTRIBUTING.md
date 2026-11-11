# Contributing

## Branching

- `main` is protected and always deployable.
- Work on short-lived branches: `feature/<topic>`, `fix/<topic>`, `chore/<topic>`.
- Open a pull request into `main`. The `ci` workflow runs only the jobs your change
  touches; its `ci-ok` check is required. Same-repository PRs are squash-merged
  automatically as soon as `ci-ok` passes (see `.github/workflows/auto-merge.yml`);
  open the PR as a draft to keep it from merging.

Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `chore:`, `ci:`, `docs:`, `refactor:`, `test:`).

## Local setup

Install [uv](https://docs.astral.sh/uv/), then:

```bash
make install      # uv sync --frozen (Python 3.14 + lint/test groups) && pre-commit install
make install-opa
```

## Before pushing

```bash
make lint       # ruff check + ruff format --check (same pinned ruff as CI)
make test       # pytest (parallel) + OPA Rego policy tests
make test-ci    # the exact `test` dependency group CI installs
```

`make ci-local` runs lint, tests, and synthetic data generation together.

## Dependencies

All Python dependencies live in `pyproject.toml` dependency groups, one per CI domain
(`test`, `drift`, `ml`, `dl`, `quality`, `feature-store`, …), resolved into a single
`uv.lock`. After editing a group run `uv lock` and commit both files; CI installs with
`--frozen` and fails if the lock is stale.

## Changing pinned tooling

- Ruff: the `lint` group in `pyproject.toml` and `.pre-commit-config.yaml`.
- OPA: `OPA_VERSION` in the `Makefile` and `ci.yml`, the `08` workflow, and
  `infra/docker-compose/docker-compose.services.yml`.
- Kyverno, actionlint, Trivy: `.github/actions/setup-kyverno`, `ci.yml`, and `13` (each
  download is checksum-verified or SHA-pinned).
- Third-party actions are pinned to full commit SHAs; `tests/unit/test_repo_contracts.py`
  enforces it.

## Policies

Rego files use Rego v1 syntax (OPA 1.x). Every policy change needs a matching
`*_test.rego` case; run `opa test aiops/policies/opa/ -v`. Kyverno policies are
`ValidatingPolicy` (CEL); add a resource and an expected result to
`aiops/policies/kyverno/tests/` and run `kyverno test aiops/policies/kyverno/tests`.
