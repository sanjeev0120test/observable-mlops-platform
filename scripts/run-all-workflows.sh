#!/usr/bin/env bash
# Run every UC eval gate on GitHub Actions via the uc-evals orchestrator
# (a manual dispatch is a full run: all 23 UCs → aggregate → portal on main).
# Usage: bash scripts/run-all-workflows.sh [--wait]
set -euo pipefail

REF="${REF:-main}"

gh workflow run uc-evals.yml --ref "$REF"
echo "Dispatched uc-evals on ref=${REF}."

if [ "${1:-}" = "--wait" ]; then
  sleep 10
  run_id="$(gh run list --workflow uc-evals.yml --branch "$REF" --event workflow_dispatch \
    --limit 1 --json databaseId --jq '.[0].databaseId')"
  gh run watch "$run_id" --exit-status
else
  echo "Monitor: gh run list --workflow uc-evals.yml --limit 5"
fi
