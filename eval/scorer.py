"""
Unified scoring engine for all 23 use cases.
Usage:
    from eval.scorer import compute_score
    result = compute_score("UC1", {"ks_statistic": 0.15, "psi_score": 0.08, ...})
    result.save()
    if not result.passed:
        sys.exit(1)  # fails CI
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from eval.metrics import UC_METRICS, THRESHOLDS, MetricSpec, EvalResult


def _score_metric(spec: MetricSpec, value: Any) -> float:
    """
    Return a 0-100 score for one metric.

    bool_true:     100 if value is truthy, else 0
    exact:         100 if value == threshold, else 0 (for counts use higher_better)
    higher_better: 100 if value >= threshold, scaled linearly below
    lower_better:  100 if value <= threshold, scaled linearly above
    """
    if spec.direction == "bool_true":
        return 100.0 if value else 0.0

    if spec.direction == "exact":
        return 100.0 if value == spec.pass_threshold else 0.0

    try:
        v = float(value)
        t = float(spec.pass_threshold)
    except (TypeError, ValueError):
        return 0.0

    if spec.direction == "higher_better":
        if t == 0:
            return 100.0 if v >= 0 else 0.0
        raw = v / t
        return min(100.0, max(0.0, raw * 100.0))

    if spec.direction == "lower_better":
        if t == 0:
            return 100.0 if v <= 0 else 0.0
        raw = 1.0 - (v - t) / (abs(t) + 1e-9)
        return min(100.0, max(0.0, raw * 100.0))

    return 0.0


def compute_score(uc: str, metric_values: dict[str, Any]) -> EvalResult:
    """
    Compute a weighted composite score [0-100] for one UC.

    Args:
        uc: Use case identifier, e.g. "UC1".
        metric_values: Dict of metric_name -> observed value.

    Returns:
        EvalResult with score, passed flag, and per-metric breakdown.
    """
    if uc not in UC_METRICS:
        raise ValueError(f"Unknown use case: {uc}. Valid values: {sorted(UC_METRICS)}")

    specs = UC_METRICS[uc]
    threshold = THRESHOLDS[uc]

    total_weight = sum(s.weight for s in specs)
    weighted_sum = 0.0
    details: dict[str, Any] = {}

    for spec in specs:
        raw_value = metric_values.get(spec.name)
        if raw_value is None:
            metric_score = 0.0
            details[spec.name] = {
                "value": None, "score": 0.0, "weight": spec.weight,
                "threshold": spec.pass_threshold, "status": "MISSING",
            }
        else:
            metric_score = _score_metric(spec, raw_value)
            details[spec.name] = {
                "value": raw_value,
                "score": round(metric_score, 2),
                "weight": spec.weight,
                "threshold": spec.pass_threshold,
                "status": "PASS" if metric_score >= 80 else "WARN" if metric_score >= 50 else "FAIL",
            }
        weighted_sum += metric_score * spec.weight

    composite = weighted_sum / total_weight if total_weight > 0 else 0.0
    passed = composite >= threshold

    return EvalResult(
        uc=uc,
        score=round(composite, 2),
        passed=passed,
        threshold=threshold,
        metrics=metric_values,
        details=details,
    )


def run_eval_gate(
    uc: str,
    metric_values: dict[str, Any],
    output_dir: Path = Path("eval-results"),
) -> None:
    """
    Run eval, save result to disk, print summary, and exit(1) if failed.
    This is called at the end of every GitHub Actions job.
    """
    result = compute_score(uc, metric_values)
    path = result.save(output_dir)
    print(f"\n{'='*60}")
    print(f"  EVAL GATE: {uc}")
    print(f"  Score:     {result.score:.1f} / 100")
    print(f"  Threshold: {result.threshold}")
    print(f"  Status:    {'PASS' if result.passed else 'FAIL'}")
    print(f"  Results:   {path}")
    print(f"{'='*60}\n")

    for metric, info in result.details.items():
        status_icon = "✓" if info["status"] == "PASS" else "~" if info["status"] == "WARN" else "✗"
        print(f"  {status_icon} {metric}: {info['value']} (score={info['score']:.0f}, status={info['status']})")

    if not result.passed:
        print(f"\n[FAIL] {uc} scored {result.score:.1f} < threshold {result.threshold} — CI gate blocked.")
        sys.exit(1)

    print(f"\n[PASS] {uc} scored {result.score:.1f} >= threshold {result.threshold}.")


def aggregate_all_results(eval_dir: Path = Path("eval-results")) -> dict:
    """Read all UC result files and produce a summary report."""
    summary: dict[str, Any] = {"passed": 0, "failed": 0, "total": 0, "ucs": {}}
    for json_file in sorted(eval_dir.glob("uc*.json")):
        data = json.loads(json_file.read_text())
        uc = data["uc"]
        summary["ucs"][uc] = {
            "score": data["score"],
            "passed": data["passed"],
            "threshold": data["threshold"],
        }
        summary["total"] += 1
        if data["passed"]:
            summary["passed"] += 1
        else:
            summary["failed"] += 1
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run eval gate for a single UC")
    parser.add_argument("uc", help="Use case ID, e.g. UC1")
    parser.add_argument("metrics_json", help="Path to JSON file with metric values")
    parser.add_argument("--output-dir", default="eval-results")
    args = parser.parse_args()

    metrics = json.loads(Path(args.metrics_json).read_text())
    run_eval_gate(args.uc, metrics, Path(args.output_dir))
