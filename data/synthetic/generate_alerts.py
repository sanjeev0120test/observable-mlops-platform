"""
Synthetic Prometheus alert stream generator.
Produces correlated alert cascades from single root causes —
used by UC3 (alert correlation & fatigue reduction).

Output schema:
  alert_id, timestamp, alertname, severity, namespace, service,
  labels_json, root_cause_id, is_duplicate
"""

import argparse
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42

ALERT_CATALOG = {
    "PodCrashLoopBackOff":   {"severity": "critical", "cascade": ["PodNotReady", "EndpointDown", "HighErrorRate"]},
    "NodeNotReady":          {"severity": "critical", "cascade": ["PodEvicted", "PodPending", "SchedulerBacklog"]},
    "HighCPUUsage":          {"severity": "warning",  "cascade": ["HighLatency", "ThrottledRequests"]},
    "OOMKilled":             {"severity": "critical", "cascade": ["PodRestarting", "HighMemUsage", "PodNotReady"]},
    "DiskPressure":          {"severity": "warning",  "cascade": ["PodEvicted", "LoggingBackpressure"]},
    "NetworkPartition":      {"severity": "critical", "cascade": ["ServiceUnreachable", "HighErrorRate", "DBConnectionFailed", "TimeoutSpike"]},
    "MLModelDrift":          {"severity": "warning",  "cascade": ["PredictionAccuracyDrop", "FeatureSkewDetected"]},
    "DeploymentRolloutStuck": {"severity": "warning", "cascade": ["PodNotReady", "ReplicasMismatch"]},
}

NAMESPACES = ["payments", "auth", "catalog", "recommendations", "gateway", "ml-serving"]


def generate_alerts(
    start: datetime,
    hours: int = 24,
    incidents_per_hour: float = 2.0,
    duplicate_multiplier: int = 8,
    output_path: Path = Path("data/synthetic/alerts.parquet"),
) -> pd.DataFrame:
    """
    Generate correlated alert cascades.

    Each incident produces 1 root alert + N cascade duplicates,
    simulating the alert storm UC3 must reduce.

    duplicate_multiplier: avg number of duplicate/cascade alerts per root cause.
    """
    rng = np.random.default_rng(SEED)
    records = []
    root_names = list(ALERT_CATALOG.keys())

    ts = start
    end = start + timedelta(hours=hours)

    while ts < end:
        next_incident = ts + timedelta(minutes=float(rng.exponential(60.0 / incidents_per_hour)))
        ts = next_incident
        if ts >= end:
            break

        root_name = rng.choice(root_names)
        root_meta = ALERT_CATALOG[root_name]
        ns = rng.choice(NAMESPACES)
        root_cause_id = str(uuid.uuid4())[:8]

        root_alert = {
            "alert_id": str(uuid.uuid4()),
            "timestamp": ts.isoformat(),
            "alertname": root_name,
            "severity": root_meta["severity"],
            "namespace": ns,
            "service": f"{ns}-svc",
            "labels_json": json.dumps({"env": "prod", "cluster": "k8s-prod-01", "namespace": ns}),
            "root_cause_id": root_cause_id,
            "is_duplicate": False,
            "is_root": True,
        }
        records.append(root_alert)

        n_cascades = int(rng.integers(2, duplicate_multiplier + 1))
        for i in range(n_cascades):
            cascade_delay = timedelta(seconds=float(rng.uniform(5, 120)))
            cascade_name = rng.choice(root_meta["cascade"]) if root_meta["cascade"] else root_name
            records.append({
                "alert_id": str(uuid.uuid4()),
                "timestamp": (ts + cascade_delay).isoformat(),
                "alertname": cascade_name,
                "severity": rng.choice(["warning", "critical"]),
                "namespace": ns if rng.random() > 0.3 else rng.choice(NAMESPACES),
                "service": f"{ns}-svc",
                "labels_json": json.dumps({"env": "prod", "cluster": "k8s-prod-01",
                                           "namespace": ns, "cascade_of": root_cause_id}),
                "root_cause_id": root_cause_id,
                "is_duplicate": True,
                "is_root": False,
            })

    df = pd.DataFrame(records)
    df = df.sort_values("timestamp").reset_index(drop=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    total = len(df)
    duplicates = df["is_duplicate"].sum()
    print(f"Generated {total} alerts ({duplicates} duplicates = {100*duplicates/total:.1f}%) → {output_path}")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic alert stream")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--incidents-per-hour", type=float, default=2.0)
    parser.add_argument("--output", type=str, default="data/synthetic/alerts.parquet")
    args = parser.parse_args()

    start_ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    generate_alerts(
        start=start_ts,
        hours=args.hours,
        incidents_per_hour=args.incidents_per_hour,
        output_path=Path(args.output),
    )
