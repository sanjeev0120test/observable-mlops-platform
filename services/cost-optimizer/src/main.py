"""
UC10 — Cloud Cost Anomaly Detector.
IsolationForest on hourly namespace cost metrics.
Reports idle resource waste and attributes cost to teams.
"""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

app = FastAPI(title="Cost Optimizer", version="0.1.0")

WASTE_RATIO = Gauge("cost_optimizer_waste_ratio", "Current waste ratio", ["namespace"])


class CostAnalysisRequest(BaseModel):
    dataset: str = "data/synthetic/cost_data.parquet"
    contamination: float = 0.04


class CostAnalysisResult(BaseModel):
    anomaly_detection_f1: float
    idle_resource_pct_identified: float
    namespace_attribution_coverage: float
    top_waste_namespaces: list[dict]
    model_version: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "cost-optimizer"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/analyze", response_model=CostAnalysisResult)
def analyze(req: CostAnalysisRequest) -> CostAnalysisResult:
    """Stub — Phase 1 implements IsolationForest on Prometheus cost metrics."""
    return CostAnalysisResult(
        anomaly_detection_f1=0.78,
        idle_resource_pct_identified=0.28,
        namespace_attribution_coverage=0.97,
        top_waste_namespaces=[
            {"namespace": "ml-serving", "waste_ratio": 0.45, "cost_usd": 25.0},
            {"namespace": "recommendations", "waste_ratio": 0.32, "cost_usd": 18.0},
        ],
        model_version="stub-v0",
    )
