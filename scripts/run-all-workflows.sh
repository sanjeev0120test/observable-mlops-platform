#!/usr/bin/env bash
# Dispatch all platform workflows on main (GitHub Actions only — no local runtime).
# Usage: bash scripts/run-all-workflows.sh [--wait]
set -euo pipefail

REF="${REF:-main}"
WAIT="${1:-}"

WORKFLOWS=(
  "00-pr-validate.yml"
  "01-observability.yml"
  "02-data-pipeline.yml"
  "03-drift-detection.yml"
  "04-log-anomaly.yml"
  "05-feature-skew.yml"
  "06-alert-correlation.yml"
  "07-predictive-scaling.yml"
  "08-self-healing.yml"
  "09-rag-runbook.yml"
  "10-model-serving.yml"
  "11-cost-optimizer.yml"
  "13-security-policy.yml"
  "14-dora-metrics.yml"
  "15-slo-monitoring.yml"
  "18-distributed-tracing.yml"
  "19-gitops-drift.yml"
  "20-data-quality.yml"
  "21-hpo.yml"
  "22-error-classification.yml"
  "23-explainability.yml"
  "24-rate-limiting.yml"
  "25-feature-monitoring.yml"
  "26-catalog-validate.yml"
)

echo "Dispatching ${#WORKFLOWS[@]} workflows on ref=${REF}..."
for wf in "${WORKFLOWS[@]}"; do
  echo "  → $wf"
  gh workflow run "$wf" --ref "$REF"
  sleep 2
done

echo ""
echo "Dispatching E2E aggregation (run after UC workflows complete)..."
gh workflow run "90-e2e-integration.yml" --ref "$REF"

echo ""
echo "Done. Monitor: gh run list --limit 30"
echo "Portal publishes after 90-e2e + 91-publish-portal complete."

if [ "$WAIT" = "--wait" ]; then
  echo "Waiting 10 minutes before checking status..."
  sleep 600
  gh run list --limit 30
fi
