"""
Synthetic pod health metrics generator.
Produces time-series data for pod CPU, memory, restart counts with seasonal patterns
and injected anomalies — used by UC1 (drift), UC4 (scaling), UC5 (feature store).

Output schema:
  timestamp, namespace, pod_name, cpu_usage_pct, mem_usage_pct,
  restart_count, ready_status, node_name, team_label
"""

import argparse
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
NAMESPACES = ["payments", "auth", "catalog", "recommendations", "gateway", "ml-serving"]
TEAMS = {"payments": "team-finance", "auth": "team-platform", "catalog": "team-data",
         "recommendations": "team-ml", "gateway": "team-infra", "ml-serving": "team-ml"}
PODS_PER_NS = 3
NODES = ["node-01", "node-02", "node-03", "node-04"]


def seasonal_load(ts: datetime, base: float = 50.0, amplitude: float = 20.0) -> float:
    """Diurnal pattern: peaks at 14:00 UTC, troughs at 04:00 UTC."""
    hour_frac = ts.hour + ts.minute / 60.0
    return base + amplitude * math.sin(2 * math.pi * (hour_frac - 6) / 24)


def generate_pod_metrics(
    start: datetime,
    hours: int = 72,
    interval_minutes: int = 5,
    anomaly_rate: float = 0.03,
    output_path: Path = Path("data/synthetic/pod_metrics.parquet"),
    drift_after_hour: int = 48,
) -> pd.DataFrame:
    """
    Generate synthetic pod metrics.

    Args:
        start: Start timestamp (UTC).
        hours: Duration in hours.
        interval_minutes: Sampling interval.
        anomaly_rate: Fraction of rows with injected anomalies.
        output_path: Where to write the Parquet file.
        drift_after_hour: After this many hours, simulate concept drift
                          (CPU usage distribution shifts by +15%).
    """
    rng = np.random.default_rng(SEED)
    records = []

    for ns in NAMESPACES:
        for pod_idx in range(1, PODS_PER_NS + 1):
            pod_name = f"{ns}-pod-{pod_idx:02d}"
            node = NODES[rng.integers(0, len(NODES))]
            restart_count = 0

            ts = start
            for step in range(int(hours * 60 / interval_minutes)):
                ts = start + timedelta(minutes=step * interval_minutes)
                is_drifted = step * interval_minutes / 60 > drift_after_hour

                base_cpu = seasonal_load(ts, base=35.0, amplitude=18.0)
                if is_drifted:
                    base_cpu += 15.0  # distribution shift — triggers UC1 drift detection

                cpu = float(np.clip(rng.normal(base_cpu, 8.0), 0, 100))
                mem = float(np.clip(rng.normal(55.0, 10.0), 0, 100))
                ready = True

                # Inject anomalies
                is_anomaly = rng.random() < anomaly_rate
                if is_anomaly:
                    anomaly_type = rng.choice(["cpu_spike", "mem_leak", "crash_loop"])
                    if anomaly_type == "cpu_spike":
                        cpu = float(rng.uniform(90, 100))
                    elif anomaly_type == "mem_leak":
                        mem = float(rng.uniform(88, 99))
                    elif anomaly_type == "crash_loop":
                        restart_count += rng.integers(1, 5)
                        ready = False

                records.append({
                    "timestamp": ts.isoformat(),
                    "namespace": ns,
                    "pod_name": pod_name,
                    "cpu_usage_pct": round(cpu, 2),
                    "mem_usage_pct": round(mem, 2),
                    "restart_count": int(restart_count),
                    "ready_status": ready,
                    "node_name": node,
                    "team_label": TEAMS[ns],
                    "is_anomaly": is_anomaly,
                    "is_drifted": is_drifted,
                })

    df = pd.DataFrame(records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    print(f"Generated {len(df)} pod metric records → {output_path}")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic pod metrics")
    parser.add_argument("--hours", type=int, default=72)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--anomaly-rate", type=float, default=0.03)
    parser.add_argument("--output", type=str, default="data/synthetic/pod_metrics.parquet")
    parser.add_argument("--drift-after-hour", type=int, default=48)
    args = parser.parse_args()

    start_ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    df = generate_pod_metrics(
        start=start_ts,
        hours=args.hours,
        interval_minutes=args.interval,
        anomaly_rate=args.anomaly_rate,
        output_path=Path(args.output),
        drift_after_hour=args.drift_after_hour,
    )
    print(df.describe())
