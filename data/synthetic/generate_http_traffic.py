"""
Synthetic HTTP traffic / request rate generator.
Produces time-series of request rate, error rate, and latency percentiles
with realistic diurnal peaks — used by UC4 (predictive scaling), UC21 (SLO monitoring).

Output schema:
  timestamp, service, requests_per_second, error_rate_pct,
  p50_latency_ms, p99_latency_ms, http_5xx_count, http_2xx_count
"""

import argparse
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42

SERVICES = {
    "payments-api":    {"base_rps": 120, "peak_rps": 400, "error_base_pct": 0.1},
    "auth-service":    {"base_rps": 200, "peak_rps": 600, "error_base_pct": 0.05},
    "catalog-svc":     {"base_rps": 80,  "peak_rps": 250, "error_base_pct": 0.2},
    "ml-serving-api":  {"base_rps": 40,  "peak_rps": 150, "error_base_pct": 0.3},
}

TARGET_SUCCESS_RATE = 0.999  # 99.9% — SLO target for UC21


def diurnal_rps(ts: datetime, base: float, peak: float) -> float:
    """Business-hours traffic pattern peaking around 14:00 UTC."""
    hour = ts.hour + ts.minute / 60.0
    factor = 0.5 + 0.5 * math.sin(2 * math.pi * (hour - 6) / 24)
    return base + (peak - base) * factor


def generate_http_traffic(
    start: datetime,
    hours: int = 72,
    interval_seconds: int = 60,
    slo_breach_window: tuple[int, int] | None = (60, 62),
    output_path: Path = Path("data/synthetic/http_traffic.parquet"),
) -> pd.DataFrame:
    """
    Generate HTTP traffic metrics.

    Args:
        slo_breach_window: Tuple (start_hour, end_hour) where error rate spikes to
                           simulate SLO budget burn — used by UC21 alerting tests.
    """
    rng = np.random.default_rng(SEED)
    records = []

    for svc, meta in SERVICES.items():
        ts = start
        for _ in range(int(hours * 3600 / interval_seconds)):
            hour_offset = (ts - start).total_seconds() / 3600

            rps = diurnal_rps(ts, meta["base_rps"], meta["peak_rps"])
            rps *= float(rng.lognormal(0, 0.08))  # natural variance

            # Inject SLO breach window
            in_breach = (slo_breach_window is not None
                         and slo_breach_window[0] <= hour_offset < slo_breach_window[1])
            error_pct = meta["error_base_pct"]
            if in_breach:
                error_pct = float(rng.uniform(5.0, 15.0))  # 5-15% error rate — burns SLO budget

            p50 = float(rng.lognormal(math.log(40), 0.3))
            p99 = p50 * float(rng.uniform(3.0, 8.0))

            total_requests = int(rps * interval_seconds)
            http_5xx = int(total_requests * error_pct / 100)
            http_2xx = total_requests - http_5xx

            records.append({
                "timestamp": ts.isoformat(),
                "service": svc,
                "requests_per_second": round(rps, 2),
                "error_rate_pct": round(error_pct, 4),
                "p50_latency_ms": round(p50, 1),
                "p99_latency_ms": round(p99, 1),
                "http_5xx_count": http_5xx,
                "http_2xx_count": http_2xx,
                "in_slo_breach": in_breach,
                "slo_met": error_pct < (1 - TARGET_SUCCESS_RATE) * 100,
            })
            ts += timedelta(seconds=interval_seconds)

    df = pd.DataFrame(records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    print(f"Generated {len(df)} traffic records → {output_path}")
    slo_breach_rows = df["in_slo_breach"].sum()
    print(f"SLO breach window: {slo_breach_rows} rows ({100*slo_breach_rows/len(df):.2f}%)")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic HTTP traffic")
    parser.add_argument("--hours", type=int, default=72)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--output", type=str, default="data/synthetic/http_traffic.parquet")
    args = parser.parse_args()

    start_ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    generate_http_traffic(
        start=start_ts,
        hours=args.hours,
        interval_seconds=args.interval,
        output_path=Path(args.output),
    )
