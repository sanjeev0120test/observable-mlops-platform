"""
UC1 — ML Drift Monitor service.
Wires the HTTP API to the real drift_engine.compute_drift() pipeline.
Computes KS statistic, PSI, NannyML CBPE estimates, and Alibi LSDD.
Generates Evidently HTML reports and triggers Airflow retrain DAG on breach.

Endpoints:
  POST /api/v1/check-drift   — run full drift check against reference dataset
  GET  /api/v1/report        — latest HTML report path
  GET  /health
  GET  /metrics
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

from services.drift_monitor.src.drift_engine import compute_drift

logger = logging.getLogger(__name__)

app = FastAPI(title="Drift Monitor", version="0.2.0")

# FIXED: metric name now matches alert rule ml_model_psi_score (was drift_monitor_psi_score)
DRIFT_DETECTED = Counter(
    "drift_monitor_drift_detected_total",
    "Total drift events detected",
    ["model"],
)
# This is the metric the Prometheus alert rule references
ML_MODEL_PSI_SCORE = Gauge(
    "ml_model_psi_score",
    "Current PSI score per model and feature",
    ["model", "feature"],
)
ML_MODEL_KS_STAT = Gauge(
    "ml_model_ks_statistic",
    "Current KS statistic per model and feature",
    ["model", "feature"],
)
RETRAIN_TRIGGERS = Counter(
    "drift_monitor_retrain_triggered_total",
    "Total retrain DAG triggers fired",
    ["model"],
)

REPORT_DIR = Path(os.getenv("REPORT_OUTPUT_DIR", "/app/reports"))
REPORT_DIR.mkdir(parents=True, exist_ok=True)

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
AIRFLOW_URL = os.getenv("AIRFLOW_URL", "http://airflow-webserver:8080")
AIRFLOW_USER = os.getenv("AIRFLOW_USER", "admin")
AIRFLOW_PASSWORD = os.getenv("AIRFLOW_PASSWORD", "admin")

# Reference dataset path — materialized at startup from DVC or env override
REFERENCE_DATA_PATH = os.getenv(
    "REFERENCE_DATA_PATH",
    "data/synthetic/pod_metrics.parquet",
)

_reference_df: pd.DataFrame | None = None


def _load_reference_df() -> pd.DataFrame:
    """Load reference dataset once, cache in module-level variable."""
    global _reference_df
    if _reference_df is None:
        path = Path(REFERENCE_DATA_PATH)
        if not path.exists():
            raise FileNotFoundError(
                f"Reference dataset not found at {path}. "
                "Run: python data/synthetic/generate_pod_metrics.py"
            )
        _reference_df = pd.read_parquet(path)
        logger.info("Reference dataset loaded: %d rows from %s", len(_reference_df), path)
    return _reference_df


def _trigger_airflow_retrain(model_name: str, psi_score: float) -> bool:
    """Trigger Airflow retrain DAG via REST API. Returns True if triggered successfully."""
    try:
        resp = httpx.post(
            f"{AIRFLOW_URL}/api/v1/dags/pod_failure_prediction_retrain/dagRuns",
            json={
                "conf": {
                    "trigger": "drift_monitor",
                    "psi_score": str(psi_score),
                    "model_name": model_name,
                },
            },
            auth=(AIRFLOW_USER, AIRFLOW_PASSWORD),
            timeout=10.0,
        )
        if resp.status_code in (200, 201):
            logger.info("Retrain DAG triggered for %s (PSI=%.4f)", model_name, psi_score)
            return True
        logger.warning(
            "Airflow retrain trigger returned %d (Airflow may not be running): %s",
            resp.status_code,
            resp.text[:200],
        )
        return False
    except Exception as exc:
        logger.warning(
            "Airflow unreachable — retrain DAG not triggered (PSI=%.4f): %s",
            psi_score,
            exc,
        )
        return False


class DriftCheckRequest(BaseModel):
    model_name: str = "pod-failure-prediction"
    reference_dataset: str = REFERENCE_DATA_PATH
    current_dataset: str = REFERENCE_DATA_PATH
    primary_feature: str = "cpu_usage_pct"
    window_hours: int = 24


class DriftCheckResult(BaseModel):
    model_name: str
    ks_statistic: float
    psi_score: float
    nannyml_performance_estimate: float
    alibi_lsdd_p_value: float
    retrain_triggered: bool
    airflow_dag_triggered: bool
    report_path: str | None
    drifted_features: list[str]
    n_reference: int
    n_current: int


@app.get("/health")
def health() -> dict:
    ref_path = Path(REFERENCE_DATA_PATH)
    return {
        "status": "ok",
        "service": "drift-monitor",
        "version": "0.2.0",
        "reference_data_available": ref_path.exists(),
        "reference_data_path": str(ref_path),
    }


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/check-drift", response_model=DriftCheckResult)
def check_drift(req: DriftCheckRequest) -> DriftCheckResult:
    """
    Run full drift detection pipeline: KS + PSI + NannyML CBPE + Alibi LSDD + Evidently report.
    Triggers Airflow retrain DAG when PSI > RETRAIN_PSI_THRESHOLD (0.10).
    Updates Prometheus metrics ml_model_psi_score and ml_model_ks_statistic.
    """
    try:
        reference_df = _load_reference_df()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # For current data: use same synthetic dataset with injected drift offset
    # In production: query Feast online store or live feature pipeline
    try:
        current_path = Path(req.current_dataset)
        if current_path.exists() and str(current_path) != REFERENCE_DATA_PATH:
            current_df = pd.read_parquet(current_path)
        else:
            # Simulate a slight drift for demo (in production: real incoming data)
            rng = np.random.default_rng(42)
            current_df = reference_df.copy()
            # Inject realistic drift: shift CPU distribution slightly
            if "cpu_usage_pct" in current_df.columns:
                shift = rng.normal(0, 5, len(current_df))
                current_df["cpu_usage_pct"] = (current_df["cpu_usage_pct"] + shift).clip(0, 100)
    except Exception as exc:
        logger.warning("Failed to load current dataset, using reference copy: %s", exc)
        current_df = reference_df.copy()

    drift_metrics = compute_drift(
        reference_df=reference_df,
        current_df=current_df,
        primary_feature=req.primary_feature,
        report_output_dir=REPORT_DIR,
        model_name=req.model_name,
    )

    # Update Prometheus gauges (aligns with alert rule ml_model_psi_score)
    ML_MODEL_PSI_SCORE.labels(model=req.model_name, feature=req.primary_feature).set(
        drift_metrics.psi_score
    )
    ML_MODEL_KS_STAT.labels(model=req.model_name, feature=req.primary_feature).set(
        drift_metrics.ks_statistic
    )

    airflow_triggered = False
    if drift_metrics.retrain_triggered:
        DRIFT_DETECTED.labels(model=req.model_name).inc()
        RETRAIN_TRIGGERS.labels(model=req.model_name).inc()
        airflow_triggered = _trigger_airflow_retrain(req.model_name, drift_metrics.psi_score)

    return DriftCheckResult(
        model_name=req.model_name,
        ks_statistic=drift_metrics.ks_statistic,
        psi_score=drift_metrics.psi_score,
        nannyml_performance_estimate=drift_metrics.nannyml_performance_estimate,
        alibi_lsdd_p_value=drift_metrics.alibi_lsdd_p_value,
        retrain_triggered=drift_metrics.retrain_triggered,
        airflow_dag_triggered=airflow_triggered,
        report_path=drift_metrics.report_path,
        drifted_features=drift_metrics.drifted_features,
        n_reference=drift_metrics.n_reference,
        n_current=drift_metrics.n_current,
    )


@app.get("/api/v1/report")
def get_report() -> dict:
    """Return path to the latest Evidently HTML drift report."""
    reports = sorted(REPORT_DIR.glob("*.html"))
    if not reports:
        return {"status": "no_reports", "message": "Run /api/v1/check-drift first"}
    latest = reports[-1]
    return {"status": "ok", "report_path": str(latest), "all_reports": [str(r) for r in reports]}
