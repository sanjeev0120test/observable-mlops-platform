# Security Policy

## Supported versions

Only the `main` branch receives security fixes.

## Reporting a vulnerability

Do **not** open a public issue for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/sanjeev0120test/observable-mlops-platform/security/advisories/new)
instead. Include:

- affected component (service, workflow, policy, manifest) and commit SHA
- reproduction steps or proof of concept
- impact assessment (confidentiality / integrity / availability)

You will get an acknowledgement within 3 business days and a remediation plan within 10.

## Built-in controls

| Control | Where |
| --- | --- |
| Least-privilege `GITHUB_TOKEN` (`contents: read` by default) | every workflow in `.github/workflows/` |
| Fail-closed policy gates (OPA / Rego v1) | `aiops/policies/opa/`, workflows `00`, `08`, `27` |
| Admission control (Kyverno: no privileged pods, required labels) | `aiops/policies/kyverno/` |
| Runtime threat detection (Falco custom rules) | `aiops/falco/custom_rules.yml` |
| SBOM (Syft), vulnerability scan (Grype, Trivy), keyless signing (Cosign) | workflow `28-sbom-signing.yml` |
| Secret scanning before commit (gitleaks, detect-private-key) | `.pre-commit-config.yaml` |
| Non-root containers with healthchecks | `services/*/Dockerfile` |
| Automated dependency updates + vulnerability alerts | `renovate.json` |

## Secrets

Never commit credentials. `.env` is git-ignored; copy `.env.example` and replace every
`CHANGE_ME` value. CI secrets (`DAGSHUB_TOKEN`, `HF_TOKEN`) live in GitHub Actions secrets.
