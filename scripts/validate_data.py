"""
Validate all generated synthetic data files.
Called by the DVC 'validate_all' stage.
Writes data/synthetic/validation_report.json with pass/fail status per file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

CHECKS: dict[str, dict] = {
    "pod_metrics.parquet": {
        "min_rows": 1000,
        "required_cols": [
            "timestamp",
            "namespace",
            "pod_name",
            "cpu_usage_pct",
            "mem_usage_pct",
            "restart_count",
            "is_anomaly",
            "is_drifted",
        ],
        "range_checks": {"cpu_usage_pct": (0, 100), "mem_usage_pct": (0, 100)},
    },
    "cost_data.parquet": {
        "min_rows": 500,
        "required_cols": ["hour", "namespace", "team_label", "hourly_cost_usd", "waste_ratio"],
        "range_checks": {"waste_ratio": (0, 1), "hourly_cost_usd": (0, None)},
    },
    "alerts.parquet": {
        "min_rows": 50,
        "required_cols": [
            "alert_id",
            "timestamp",
            "alertname",
            "severity",
            "root_cause_id",
            "is_duplicate",
        ],
        "duplicate_rate_min": 0.30,
    },
    "http_traffic.parquet": {
        "min_rows": 100,
        "required_cols": ["timestamp", "service", "requests_per_second", "error_rate_pct"],
        "range_checks": {"requests_per_second": (0, None), "error_rate_pct": (0, 100)},
    },
}

NDJSON_CHECKS: dict[str, dict] = {
    "container_logs.ndjson": {
        "min_lines": 500,
        "required_keys": ["timestamp", "level", "service", "message", "is_anomaly"],
    },
}


def validate_parquet(data_dir: Path) -> dict[str, dict]:
    results = {}
    for fname, spec in CHECKS.items():
        path = data_dir / fname
        if not path.exists():
            results[fname] = {"status": "MISSING", "error": f"{path} not found"}
            continue
        try:
            df = pd.read_parquet(path)
            errors = []
            if len(df) < spec["min_rows"]:
                errors.append(f"rows {len(df)} < min {spec['min_rows']}")
            for col in spec["required_cols"]:
                if col not in df.columns:
                    errors.append(f"missing column: {col}")
            for col, (lo, hi) in spec.get("range_checks", {}).items():
                if col in df.columns:
                    if lo is not None and df[col].min() < lo:
                        errors.append(f"{col} min {df[col].min()} < {lo}")
                    if hi is not None and df[col].max() > hi:
                        errors.append(f"{col} max {df[col].max()} > {hi}")
            if "duplicate_rate_min" in spec:
                dup_rate = df["is_duplicate"].mean()
                if dup_rate < spec["duplicate_rate_min"]:
                    errors.append(f"duplicate rate {dup_rate:.2f} < {spec['duplicate_rate_min']}")
            results[fname] = {
                "status": "PASS" if not errors else "FAIL",
                "rows": len(df),
                "errors": errors,
            }
        except Exception as exc:
            results[fname] = {"status": "ERROR", "error": str(exc)}
    return results


def validate_ndjson(data_dir: Path) -> dict[str, dict]:
    results = {}
    for fname, spec in NDJSON_CHECKS.items():
        path = data_dir / fname
        if not path.exists():
            results[fname] = {"status": "MISSING", "error": f"{path} not found"}
            continue
        try:
            lines = path.read_text().splitlines()
            errors = []
            if len(lines) < spec["min_lines"]:
                errors.append(f"lines {len(lines)} < min {spec['min_lines']}")
            if lines:
                sample = json.loads(lines[0])
                for key in spec["required_keys"]:
                    if key not in sample:
                        errors.append(f"missing key: {key}")
            results[fname] = {
                "status": "PASS" if not errors else "FAIL",
                "lines": len(lines),
                "errors": errors,
            }
        except Exception as exc:
            results[fname] = {"status": "ERROR", "error": str(exc)}
    return results


def main() -> None:
    data_dir = Path("data/synthetic")
    report_path = data_dir / "validation_report.json"

    parquet_results = validate_parquet(data_dir)
    ndjson_results = validate_ndjson(data_dir)

    all_results = {**parquet_results, **ndjson_results}
    passed = sum(1 for r in all_results.values() if r["status"] == "PASS")
    failed = sum(1 for r in all_results.values() if r["status"] != "PASS")

    report = {
        "summary": {"passed": passed, "failed": failed, "total": len(all_results)},
        "files": all_results,
    }

    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))

    if failed > 0:
        print(f"\n[FAIL] {failed} data validation checks failed.", file=sys.stderr)
        sys.exit(1)

    print(f"\n[PASS] All {passed} data validation checks passed.")


if __name__ == "__main__":
    main()
