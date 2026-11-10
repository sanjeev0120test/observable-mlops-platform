"""Smoke tests: every synthetic data generator runs and emits the columns the UC gates read."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

GEN_DIR = Path(__file__).parent.parent.parent / "data" / "synthetic"


def _run(script: str, out: Path, *args: str) -> Path:
    subprocess.run(
        [sys.executable, str(GEN_DIR / script), *args, "--output", str(out)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.exists() and out.stat().st_size > 0, f"{script} wrote nothing"
    return out


@pytest.fixture(scope="module")
def outdir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("synthetic")


def test_pod_metrics(outdir):
    df = pd.read_parquet(_run("generate_pod_metrics.py", outdir / "pod.parquet", "--hours", "4"))
    assert len(df) > 0
    assert df["cpu_usage_pct"].between(0, 100).all()


def test_container_logs(outdir):
    path = _run(
        "generate_container_logs.py",
        outdir / "logs.ndjson",
        "--hours",
        "1",
        "--logs-per-second",
        "1",
    )
    first = json.loads(path.read_text().splitlines()[0])
    assert {"timestamp", "level"} <= set(first)


def test_cost_data(outdir):
    df = pd.read_parquet(_run("generate_cost_data.py", outdir / "cost.parquet", "--days", "2"))
    assert "hourly_cost_usd" in df.columns


def test_alerts_have_uc3_duplicate_rate(outdir):
    df = pd.read_parquet(_run("generate_alerts.py", outdir / "alerts.parquet", "--hours", "4"))
    assert "root_cause_id" in df.columns
    assert df["is_duplicate"].mean() > 0.3


def test_http_traffic(outdir):
    df = pd.read_parquet(_run("generate_http_traffic.py", outdir / "http.parquet", "--hours", "4"))
    assert "requests_per_second" in df.columns
