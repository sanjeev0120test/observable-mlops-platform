"""
UC4 — Predictive Autoscaler service.
Prophet time-series forecasting of request load; fires KEDA ScaledObject pre-emptively.
"""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

app = FastAPI(title="Predictive Scaler", version="0.1.0")

FORECAST_MAE = Gauge("predictive_scaler_forecast_mae", "Forecast MAE as pct of mean load")


class ForecastRequest(BaseModel):
    service: str
    horizon_minutes: int = 30


class ForecastResult(BaseModel):
    service: str
    forecast_mae: float
    pre_scale_lead_time_seconds: float
    p99_latency_delta_pct: float
    scale_recommendation: dict


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "predictive-scaler"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/forecast", response_model=ForecastResult)
def forecast(req: ForecastRequest) -> ForecastResult:
    """Stub — Phase 1 implements Prophet forecasting from Prometheus metrics."""
    return ForecastResult(
        service=req.service,
        forecast_mae=0.08,
        pre_scale_lead_time_seconds=450.0,
        p99_latency_delta_pct=-0.15,
        scale_recommendation={"replicas": 3, "trigger": "KEDA ScaledObject"},
    )
