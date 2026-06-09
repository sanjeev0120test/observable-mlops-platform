"""
Synthetic cloud cost data generator.
Produces hourly namespace-level cost data with idle resource waste spikes —
used by UC10 (cost anomaly detection + attribution).

Output schema:
  hour, namespace, team_label, cpu_requested, cpu_actual, mem_requested_gi,
  mem_actual_gi, hourly_cost_usd, waste_ratio, is_anomaly
"""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42

NAMESPACE_COSTS = {
    "payments":        {"base_cost": 12.0,  "team": "team-finance"},
    "auth":            {"base_cost": 4.0,   "team": "team-platform"},
    "catalog":         {"base_cost": 6.0,   "team": "team-data"},
    "recommendations": {"base_cost": 18.0,  "team": "team-ml"},
    "gateway":         {"base_cost": 3.0,   "team": "team-infra"},
    "ml-serving":      {"base_cost": 25.0,  "team": "team-ml"},
}

USD_PER_CPU_HOUR = 0.048
USD_PER_GI_HOUR = 0.006


def generate_cost_data(
    start: datetime,
    days: int = 30,
    anomaly_rate: float = 0.04,
    output_path: Path = Path("data/synthetic/cost_data.parquet"),
) -> pd.DataFrame:
    """
    Generate hourly cost per namespace with injected waste anomalies.

    Waste anomaly: CPU/memory is requested but barely used (idle resources).
    This is the pattern IsolationForest in UC10 must detect.
    """
    rng = np.random.default_rng(SEED)
    records = []

    for ns, meta in NAMESPACE_COSTS.items():
        ts = start
        for _ in range(days * 24):
            cpu_requested = float(rng.uniform(2.0, 16.0))
            cpu_actual = cpu_requested * float(rng.uniform(0.35, 0.80))

            mem_requested = float(rng.uniform(4.0, 32.0))
            mem_actual = mem_requested * float(rng.uniform(0.40, 0.85))

            is_anomaly = rng.random() < anomaly_rate
            if is_anomaly:
                # Anomaly: high request, very low actual (idle waste)
                cpu_actual = cpu_requested * float(rng.uniform(0.02, 0.10))
                mem_actual = mem_requested * float(rng.uniform(0.03, 0.12))

            hourly_cost = (
                cpu_requested * USD_PER_CPU_HOUR
                + mem_requested * USD_PER_GI_HOUR
                + float(rng.normal(0, 0.5))
            )
            hourly_cost = max(0.01, hourly_cost)
            waste_ratio = 1.0 - (
                0.5 * (cpu_actual / cpu_requested) + 0.5 * (mem_actual / mem_requested)
            )

            records.append({
                "hour": ts.isoformat(),
                "namespace": ns,
                "team_label": meta["team"],
                "cpu_requested": round(cpu_requested, 3),
                "cpu_actual": round(cpu_actual, 3),
                "mem_requested_gi": round(mem_requested, 3),
                "mem_actual_gi": round(mem_actual, 3),
                "hourly_cost_usd": round(hourly_cost, 4),
                "waste_ratio": round(waste_ratio, 4),
                "is_anomaly": is_anomaly,
            })
            ts += timedelta(hours=1)

    df = pd.DataFrame(records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    print(f"Generated {len(df)} cost records → {output_path}")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic cost data")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--anomaly-rate", type=float, default=0.04)
    parser.add_argument("--output", type=str, default="data/synthetic/cost_data.parquet")
    args = parser.parse_args()

    start_ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    df = generate_cost_data(
        start=start_ts,
        days=args.days,
        anomaly_rate=args.anomaly_rate,
        output_path=Path(args.output),
    )
    print(df.groupby("team_label")["hourly_cost_usd"].sum())
