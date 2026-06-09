"""
UC1 — ML Drift Monitor service.
Computes KS statistic, PSI, and NannyML CBPE estimates.
Generates Evidently HTML reports and triggers Airflow retrain DAG on breach.
Endpoints:
  POST /api/v1/check-drift   — run full drift check
  GET  /api/v1/report        — latest HTML report path
  GET  /health
  GET  /metrics
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

app = FastAPI(title="Drift Monitor", version="0.1.0")

DRIFT_DETECTED = Counter("drift_monitor_drift_detected_total", "Total drift events detected", ["model"])
CURRENT_PSI = Gauge("drift_monitor_psi_score", "Current PSI score", ["model", "feature"])

REPORT_DIR = Path(os.getenv("REPORT_OUTPUT_DIR", "/app/reports"))
REPORT_DIR.mkdir(parents=True, exist_ok=True)

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")


class DriftCheckRequest(BaseModel):
    model_name: str
    reference_dataset: str = "data/synthetic/pod_metrics.parquet"
    current_dataset: str = "data/synthetic/pod_metrics.parquet"


class DriftCheckResult(BaseModel):
    model_name: str
    ks_statistic: float
    psi_score: float
    nannyml_performance_estimate: float
    alibi_lsdd_p_value: float
    retrain_triggered: bool
    report_path: str | None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "drift-monitor"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/check-drift", response_model=DriftCheckResult)
def check_drift(req: DriftCheckRequest) -> DriftCheckResult:
    """
    Stub drift check. Phase 1 implements the full Evidently + NannyML + Alibi pipeline.
    Returns deterministic values for Phase 0 CI green-path validation.
    """
    result = DriftCheckResult(
        model_name=req.model_name,
        ks_statistic=0.08,
        psi_score=0.06,
        nannyml_performance_estimate=0.92,
        alibi_lsdd_p_value=0.42,
        retrain_triggered=False,
        report_path=None,
    )
    CURRENT_PSI.labels(model=req.model_name, feature="cpu_usage_pct").set(result.psi_score)
    return result
