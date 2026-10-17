# Contributing

## Branching

- `main` is protected and always deployable.
- Work on short-lived branches: `feature/<topic>`, `fix/<topic>`, `chore/<topic>`.
- Open a pull request into `main`; the `00 · PR Validate` and `27 · Platform Unit Tests`
  workflows must be green before merge.

Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `chore:`, `ci:`, `docs:`, `refactor:`, `test:`).

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install numpy pandas pyarrow scipy scikit-learn httpx fastapi pydantic prometheus-client
pre-commit install
make install-opa
```

## Before pushing

```bash
make lint       # ruff + black (same pinned versions as CI)
make test       # pytest unit tests + OPA Rego policy tests
```

`make ci-local` runs lint, tests, and synthetic data generation together.

## Changing pinned tooling

Ruff and Black versions are pinned in three places that must stay in sync:
`pyproject.toml` (`[project.optional-dependencies].dev`), `.pre-commit-config.yaml`, and
`.github/workflows/00-pr-validate.yml`. OPA is pinned in the `Makefile`, the workflows, and
`infra/docker-compose/docker-compose.services.yml`.

## Policies

Rego files use Rego v1 syntax (OPA 1.x). Every policy change needs a matching
`*_test.rego` case; run `opa test aiops/policies/opa/ -v`.
