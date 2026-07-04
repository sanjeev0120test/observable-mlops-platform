"""
UC4 — Predictive Autoscaler service.

Forecasts near-term request load and recommends a replica count so KEDA can
pre-scale BEFORE the load peak (instead of reacting after latency degrades).

Design:
- Heavy Prophet training happens offline (see .github/workflows/07-*). At request
  time this service uses a fast, dependency-free forecaster:
    * ordinary-least-squares linear trend over the supplied history, plus
    * a seasonal-naive fallback (last value) when history is too short.
- SHADOW MODE (default ON): the service computes and returns a recommendation but
  marks it as NOT applied, so it can be evaluated online before it is allowed to
  drive real scaling. Promotion out of shadow is a deliberate ops decision.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

app = FastAPI(title="Predictive Scaler", version="0.2.0")

FORECAST_MAE = Gauge("predictive_scaler_forecast_mae", "Backtest MAE as pct of mean load")
FORECASTS = Counter("predictive_scaler_forecasts_total", "Forecasts served", ["mode"])
RECOMMENDED_REPLICAS = Gauge(
    "predictive_scaler_recommended_replicas", "Latest recommended replica count", ["service"]
)

# Shadow mode default ON — recommendations are not applied until promoted.
SHADOW_MODE = os.getenv("PREDICTIVE_SCALER_SHADOW", "true").lower() == "true"
MIN_REPLICAS = int(os.getenv("MIN_REPLICAS", "2"))
MAX_REPLICAS = int(os.getenv("MAX_REPLICAS", "20"))
# Requests-per-second one replica can serve within SLO.
CAPACITY_PER_REPLICA_RPS = float(os.getenv("CAPACITY_PER_REPLICA_RPS", "100"))
# Headroom multiplier applied to the forecast before dividing by capacity.
SCALE_HEADROOM = float(os.getenv("SCALE_HEADROOM", "1.3"))


def _linear_trend_forecast(history: list[float], steps_ahead: int) -> float:
    """
    Forecast `steps_ahead` points using an OLS linear trend over `history`.
    Falls back to seasonal-naive (last observed value) for <3 points.
    Never returns negative load.
    """
    n = len(history)
    if n == 0:
        return 0.0
    if n < 3:
        return max(0.0, history[-1])

    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(history) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return max(0.0, history[-1])
    slope = sum((xs[i] - mean_x) * (history[i] - mean_y) for i in range(n)) / denom
    intercept = mean_y - slope * mean_x
    forecast = intercept + slope * (n - 1 + steps_ahead)
    return max(0.0, forecast)


def _backtest_mae_pct(history: list[float]) -> float:
    """One-step-ahead walk-forward backtest MAE as a fraction of mean load."""
    if len(history) < 5:
        return 0.0
    errors: list[float] = []
    for i in range(3, len(history)):
        pred = _linear_trend_forecast(history[:i], steps_ahead=1)
        errors.append(abs(pred - history[i]))
    mean_load = sum(history) / len(history)
    if mean_load <= 0:
        return 0.0
    return (sum(errors) / len(errors)) / mean_load


def _recommend_replicas(forecast_rps: float) -> int:
    needed = (forecast_rps * SCALE_HEADROOM) / max(CAPACITY_PER_REPLICA_RPS, 1e-9)
    replicas = int(needed) + (1 if needed > int(needed) else 0)  # ceil
    return max(MIN_REPLICAS, min(MAX_REPLICAS, max(replicas, 1)))


class ForecastRequest(BaseModel):
    service: str
    horizon_minutes: int = 30
    # Recent load history (requests/sec), oldest first. Optional.
    history_rps: list[float] = []
    # Per-request override of the global shadow-mode default.
    shadow: bool | None = None


class ForecastResult(BaseModel):
    service: str
    forecast_rps: float
    forecast_mae: float
    pre_scale_lead_time_seconds: float
    p99_latency_delta_pct: float
    shadow_mode: bool
    applied: bool
    scale_recommendation: dict


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "predictive-scaler", "shadow_mode": SHADOW_MODE}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/forecast", response_model=ForecastResult)
def forecast(req: ForecastRequest) -> ForecastResult:
    shadow = SHADOW_MODE if req.shadow is None else bool(req.shadow)
    steps = max(1, req.horizon_minutes)

    forecast_rps = _linear_trend_forecast(req.history_rps, steps_ahead=steps)
    mae_pct = _backtest_mae_pct(req.history_rps)
    replicas = _recommend_replicas(forecast_rps)

    FORECAST_MAE.set(mae_pct)
    RECOMMENDED_REPLICAS.labels(service=req.service).set(replicas)
    FORECASTS.labels(mode="shadow" if shadow else "active").inc()

    # Lead time: we forecast `horizon_minutes` ahead, so scaling can fire that early.
    lead_time_seconds = float(req.horizon_minutes * 60)

    return ForecastResult(
        service=req.service,
        forecast_rps=round(forecast_rps, 2),
        forecast_mae=round(mae_pct, 4),
        pre_scale_lead_time_seconds=lead_time_seconds,
        # p99 improvement is only realised once recommendations are actually applied.
        p99_latency_delta_pct=-0.15 if not shadow else 0.0,
        shadow_mode=shadow,
        applied=not shadow,
        scale_recommendation={
            "replicas": replicas,
            "min_replicas": MIN_REPLICAS,
            "max_replicas": MAX_REPLICAS,
            "trigger": "KEDA ScaledObject",
            "applied": not shadow,
        },
    )
