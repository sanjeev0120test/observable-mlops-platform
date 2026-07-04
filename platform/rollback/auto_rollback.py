"""
Model Rollback Automation Engine — UC6 / UC9.
Monitors model performance metrics and triggers automatic rollback to last-known-good version
when performance degrades beyond configured thresholds.

Architecture:
- Polls MLflow for champion/challenger model metrics
- Compares against rollback thresholds (configurable per model)
- Calls self-healing /api/v1/remediate when rollback is warranted
- Uses fail-closed OPA policy via self-healing service (never bypass OPA)
- All rollbacks are dry-run by default (ROLLBACK_DRY_RUN=true)

Production deployment: runs as a Kubernetes CronJob every 5 minutes.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("rollback-engine")

MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
SELF_HEALING_URL = os.getenv("SELF_HEALING_URL", "http://self-healing:8000")
DRY_RUN = os.getenv("ROLLBACK_DRY_RUN", "true").lower() == "true"

# Rollback thresholds per model — trigger rollback when metrics fall below these
MODEL_ROLLBACK_THRESHOLDS: dict[str, dict[str, float]] = {
    "pod-failure-prediction": {
        "accuracy": 0.70,
        "f1_score": 0.65,
        "drift_psi": 0.25,  # High PSI = significant drift → rollback
    },
    "log-anomaly-detector": {
        "reconstruction_error": 0.15,  # Above threshold = model degraded
        "precision_at_10": 0.60,
    },
    "cost-anomaly-detector": {
        "precision": 0.70,
        "recall": 0.65,
    },
}


@dataclass
class RollbackDecision:
    model_name: str
    current_version: str
    rollback_to_version: str | None
    should_rollback: bool
    reasons: list[str]
    dry_run: bool
    remediation_result: dict[str, Any] | None = None


def _get_champion_metrics(model_name: str) -> dict[str, float]:
    """
    Fetch the currently deployed (Production/Champion) model's latest run metrics from MLflow.
    Returns empty dict if MLflow is unavailable.
    """
    try:
        resp = httpx.get(
            f"{MLFLOW_URL}/api/2.0/mlflow/registered-models/get",
            params={"name": model_name},
            timeout=10.0,
        )
        resp.raise_for_status()
        model_info = resp.json().get("registered_model", {})
        aliases = model_info.get("aliases", [])

        # Find the champion/production alias version
        champion_version = None
        for alias in aliases:
            if alias.get("alias") in ("champion", "production", "Production"):
                champion_version = alias.get("version")
                break

        if not champion_version:
            latest_versions = model_info.get("latest_versions", [])
            prod_versions = [v for v in latest_versions if v.get("current_stage") == "Production"]
            if prod_versions:
                champion_version = prod_versions[0].get("version")

        if not champion_version:
            logger.debug("No champion version found for %s — using latest", model_name)
            return {}

        # Get run metrics for the champion version
        version_resp = httpx.get(
            f"{MLFLOW_URL}/api/2.0/mlflow/model-versions/get",
            params={"name": model_name, "version": champion_version},
            timeout=10.0,
        )
        version_resp.raise_for_status()
        run_id = version_resp.json().get("model_version", {}).get("run_id")
        if not run_id:
            return {}

        run_resp = httpx.get(
            f"{MLFLOW_URL}/api/2.0/mlflow/runs/get",
            params={"run_id": run_id},
            timeout=10.0,
        )
        run_resp.raise_for_status()
        metrics_list = run_resp.json().get("run", {}).get("data", {}).get("metrics", [])
        return {m["key"]: m["value"] for m in metrics_list}

    except Exception as exc:
        logger.warning("Could not fetch MLflow metrics for %s: %s", model_name, exc)
        return {}


def _find_stable_previous_version(model_name: str, current_version: str) -> str | None:
    """Find the most recent version before current that was in Production (last-known-good)."""
    try:
        resp = httpx.get(
            f"{MLFLOW_URL}/api/2.0/mlflow/model-versions/search",
            params={"filter": f"name='{model_name}'", "max_results": 20},
            timeout=10.0,
        )
        resp.raise_for_status()
        versions = resp.json().get("model_versions", [])
        # Find versions older than current that were previously in Production
        current_int = int(current_version) if current_version.isdigit() else 0
        candidates = [
            v for v in versions
            if int(v.get("version", 0)) < current_int
            and v.get("current_stage") in ("Production", "Staging", "Archived")
        ]
        if candidates:
            # Sort descending by version number, take latest
            candidates.sort(key=lambda v: int(v.get("version", 0)), reverse=True)
            return candidates[0]["version"]
    except Exception as exc:
        logger.warning("Could not find previous version for %s: %s", model_name, exc)
    return None


def check_rollback_needed(model_name: str) -> RollbackDecision:
    """
    Evaluate whether a model needs to be rolled back.
    Compares live metrics against rollback thresholds.
    """
    thresholds = MODEL_ROLLBACK_THRESHOLDS.get(model_name, {})
    if not thresholds:
        return RollbackDecision(
            model_name=model_name,
            current_version="unknown",
            rollback_to_version=None,
            should_rollback=False,
            reasons=[f"No rollback thresholds configured for {model_name}"],
            dry_run=DRY_RUN,
        )

    metrics = _get_champion_metrics(model_name)
    if not metrics:
        logger.debug("No live metrics for %s — skipping rollback check", model_name)
        return RollbackDecision(
            model_name=model_name,
            current_version="unknown",
            rollback_to_version=None,
            should_rollback=False,
            reasons=["No live metrics available from MLflow"],
            dry_run=DRY_RUN,
        )

    reasons = []
    for metric_name, threshold in thresholds.items():
        live_value = metrics.get(metric_name)
        if live_value is None:
            continue
        # Higher-better metrics: rollback if below threshold
        # Lower-better metrics (drift_psi, reconstruction_error): rollback if above threshold
        is_lower_better = metric_name in ("drift_psi", "reconstruction_error", "false_positive_rate")
        if is_lower_better and live_value > threshold:
            reasons.append(
                f"{metric_name}={live_value:.4f} exceeds rollback threshold {threshold:.4f}"
            )
        elif not is_lower_better and live_value < threshold:
            reasons.append(
                f"{metric_name}={live_value:.4f} below rollback threshold {threshold:.4f}"
            )

    current_version = metrics.get("mlflow_version", "unknown")
    rollback_to = None
    if reasons:
        rollback_to = _find_stable_previous_version(model_name, str(current_version))

    return RollbackDecision(
        model_name=model_name,
        current_version=str(current_version),
        rollback_to_version=rollback_to,
        should_rollback=bool(reasons),
        reasons=reasons,
        dry_run=DRY_RUN,
    )


def execute_rollback(decision: RollbackDecision) -> RollbackDecision:
    """
    Submit a rollback_deployment action to the self-healing service.
    The self-healing service enforces OPA policy (fail-closed).
    """
    if not decision.should_rollback:
        return decision

    if not decision.rollback_to_version:
        logger.warning(
            "Rollback needed for %s but no previous stable version found",
            decision.model_name,
        )
        return decision

    logger.info(
        "ROLLBACK: %s v%s → v%s (reasons: %s) [dry_run=%s]",
        decision.model_name,
        decision.current_version,
        decision.rollback_to_version,
        "; ".join(decision.reasons),
        decision.dry_run,
    )

    try:
        resp = httpx.post(
            f"{SELF_HEALING_URL}/api/v1/remediate",
            json={
                "action": "rollback_deployment",
                "target": {
                    "namespace": "ml-serving",
                    "deployment": decision.model_name,
                    "rollback_to_version": decision.rollback_to_version,
                },
                "trigger": {
                    "alert_name": "MLModelPerformanceDegraded",
                    "severity": "critical",
                    "reasons": decision.reasons,
                    "source": "rollback-engine",
                },
                "dry_run": decision.dry_run,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        decision.remediation_result = resp.json()
        logger.info(
            "Rollback %s: allowed=%s executed=%s",
            decision.model_name,
            decision.remediation_result.get("allowed"),
            decision.remediation_result.get("executed"),
        )
    except httpx.HTTPStatusError as exc:
        # 503 means OPA is down — fail-closed, rollback blocked, log and continue
        if exc.response.status_code == 503:
            logger.error(
                "Rollback BLOCKED: OPA policy engine unreachable (fail-closed). "
                "Model %s may be degraded. Manual intervention required.",
                decision.model_name,
            )
        else:
            logger.error("Self-healing service error: %s", exc)
    except Exception as exc:
        logger.error("Failed to submit rollback for %s: %s", decision.model_name, exc)

    return decision


def run_rollback_loop() -> list[RollbackDecision]:
    """Check all configured models and execute rollbacks as needed."""
    decisions = []
    for model_name in MODEL_ROLLBACK_THRESHOLDS:
        decision = check_rollback_needed(model_name)
        if decision.should_rollback:
            decision = execute_rollback(decision)
        decisions.append(decision)
        logger.info(
            "Rollback check %s: should_rollback=%s reasons=%d",
            model_name,
            decision.should_rollback,
            len(decision.reasons),
        )
    return decisions


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    results = run_rollback_loop()
    rollbacks_triggered = sum(1 for r in results if r.should_rollback)
    print(f"\nRollback engine complete: {rollbacks_triggered}/{len(results)} models need rollback")
    for r in results:
        if r.should_rollback:
            print(f"  ROLLBACK {r.model_name}: {'; '.join(r.reasons)}")
