"""
Synthetic container log generator.
Produces structured JSON log lines representing normal operations with injected
error bursts and OOMKilled events — used by UC2 (log anomaly), UC16 (error classification).

Output: NDJSON file where each line is a log entry.
"""

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

SEED = 42

SERVICES = ["payments-api", "auth-service", "catalog-svc", "recommendation-engine",
            "gateway", "ml-serving-api"]

NORMAL_MESSAGES = [
    "Request processed successfully",
    "Database query completed in {ms}ms",
    "Cache hit for key {key}",
    "Health check passed",
    "Feature vector fetched from Feast online store",
    "Model inference completed in {ms}ms",
    "Kafka message published to topic {topic}",
    "Redis SET key={key} ttl=300",
    "gRPC call to {svc} returned OK",
    "Prometheus metrics scraped",
]

ERROR_TEMPLATES = {
    "OOMKilled":       "OOMKilled: container exceeded memory limit {limit}Mi",
    "CrashLoopBackOff": "Back-off restarting failed container: exit code {code}",
    "ConnectionRefused": "Connection refused to {host}:{port}",
    "TimeoutError":    "Request timed out after {timeout}ms waiting for {svc}",
    "DBError":         "Database connection pool exhausted: {pool_size} connections in use",
    "ModelLoadError":  "Failed to load model artifact from {path}: FileNotFoundError",
    "FeatureSkew":     "Feature value out of expected range: {feature}={value} (expected < {max})",
    "KafkaLag":        "Consumer lag on partition {part} exceeded threshold: {lag} messages",
    "NullPointer":     "NullPointerException in {class_name}.{method}:{line}",
    "AuthFailure":     "Authentication failed: JWT signature verification error",
}

LEVELS = ["INFO", "INFO", "INFO", "INFO", "DEBUG", "WARN", "ERROR"]


def _fmt(template: str, rng: np.random.Generator) -> str:
    return template.format(
        ms=rng.integers(5, 500),
        key=f"key_{rng.integers(1000, 9999)}",
        topic=rng.choice(["events", "metrics", "alerts"]),
        svc=rng.choice(SERVICES),
        host=f"10.0.{rng.integers(1,10)}.{rng.integers(1,254)}",
        port=rng.choice([5432, 6379, 9092, 8080]),
        timeout=rng.integers(1000, 30000),
        limit=rng.integers(256, 2048),
        code=rng.integers(1, 255),
        pool_size=rng.integers(10, 50),
        path=f"/models/{rng.integers(1,100)}/artifact.pt",
        feature=rng.choice(["cpu_usage_pct", "mem_usage_pct", "restart_count"]),
        value=round(float(rng.uniform(100, 200)), 2),
        max=rng.integers(80, 100),
        part=rng.integers(0, 8),
        lag=rng.integers(1000, 50000),
        class_name=rng.choice(["PaymentService", "ModelServer", "FeatureClient"]),
        method=rng.choice(["predict", "fetch", "validate"]),
        line=rng.integers(50, 500),
    )


def generate_container_logs(
    start: datetime,
    hours: int = 24,
    logs_per_second: float = 10.0,
    error_burst_probability: float = 0.005,
    output_path: Path = Path("data/synthetic/container_logs.ndjson"),
) -> int:
    """
    Generate synthetic container logs with normal operations and error bursts.

    Error bursts simulate correlated failures (same root cause → multiple errors)
    which is the primary pattern UC2 LSTM must learn to detect.
    """
    rng = np.random.default_rng(SEED)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    interval_seconds = 1.0 / logs_per_second

    with output_path.open("w") as f:
        ts = start
        end = start + timedelta(hours=hours)
        in_burst = False
        burst_remaining = 0
        burst_service = None

        while ts < end:
            is_burst_start = not in_burst and rng.random() < error_burst_probability
            if is_burst_start:
                in_burst = True
                burst_remaining = int(rng.integers(20, 80))
                burst_service = rng.choice(SERVICES)

            if in_burst and burst_remaining > 0:
                error_type = rng.choice(list(ERROR_TEMPLATES.keys()))
                record = {
                    "timestamp": ts.isoformat(),
                    "level": "ERROR",
                    "service": burst_service,
                    "pod": f"{burst_service}-{rng.integers(1,4):02d}",
                    "message": _fmt(ERROR_TEMPLATES[error_type], rng),
                    "error_type": error_type,
                    "is_anomaly": True,
                    "burst_id": f"burst_{ts.strftime('%Y%m%d%H%M%S')}",
                }
                burst_remaining -= 1
                if burst_remaining == 0:
                    in_burst = False
            else:
                svc = rng.choice(SERVICES)
                template = rng.choice(NORMAL_MESSAGES)
                record = {
                    "timestamp": ts.isoformat(),
                    "level": rng.choice(LEVELS),
                    "service": svc,
                    "pod": f"{svc}-{rng.integers(1,4):02d}",
                    "message": _fmt(template, rng),
                    "error_type": None,
                    "is_anomaly": False,
                    "burst_id": None,
                }

            f.write(json.dumps(record) + "\n")
            total += 1
            ts += timedelta(seconds=interval_seconds + float(rng.exponential(0.02)))

    print(f"Generated {total} log lines → {output_path}")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic container logs")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--logs-per-second", type=float, default=10.0)
    parser.add_argument("--output", type=str, default="data/synthetic/container_logs.ndjson")
    args = parser.parse_args()

    start_ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    generate_container_logs(
        start=start_ts,
        hours=args.hours,
        logs_per_second=args.logs_per_second,
        output_path=Path(args.output),
    )
