"""
UC2 — Log Anomaly Detector service.
LSTM autoencoder trained on normal log embeddings; detects reconstruction error spikes.
Endpoints:
  POST /api/v1/detect    — ingest log batch, return anomaly scores
  GET  /api/v1/similar   — query Qdrant for similar past incidents
  GET  /health           — liveness check
  GET  /metrics          — Prometheus metrics
"""

from __future__ import annotations

import os
import time
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

app = FastAPI(title="Anomaly Detector", version="0.1.0")

ANOMALY_COUNTER = Counter("anomaly_detector_anomalies_total", "Total anomalies detected")
DETECT_LATENCY = Histogram("anomaly_detector_detect_latency_seconds", "Detection latency")

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = "log_anomaly_incidents"

# Stub threshold — replaced by trained model value at runtime
RECONSTRUCTION_LOSS_THRESHOLD = float(os.getenv("LOSS_THRESHOLD", "0.05"))


class LogBatch(BaseModel):
    logs: list[str]
    service: str = "unknown"
    window_id: str = ""


class AnomalyResult(BaseModel):
    window_id: str
    anomaly_scores: list[float]
    anomalies_detected: int
    threshold: float
    similar_incidents: list[dict]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "anomaly-detector"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/detect", response_model=AnomalyResult)
def detect_anomalies(batch: LogBatch) -> AnomalyResult:
    start = time.time()

    # Stub: score = random noise (real impl: LSTM autoencoder reconstruction error)
    rng = np.random.default_rng(hash(batch.window_id) % (2**31))
    scores = rng.exponential(0.03, size=len(batch.logs)).tolist()
    n_anomalies = sum(1 for s in scores if s > RECONSTRUCTION_LOSS_THRESHOLD)

    if n_anomalies > 0:
        ANOMALY_COUNTER.inc(n_anomalies)

    DETECT_LATENCY.observe(time.time() - start)

    return AnomalyResult(
        window_id=batch.window_id,
        anomaly_scores=scores,
        anomalies_detected=n_anomalies,
        threshold=RECONSTRUCTION_LOSS_THRESHOLD,
        similar_incidents=[],  # populated after Qdrant is seeded in Phase 1
    )


@app.get("/api/v1/similar")
def similar_incidents(query: str, top_k: int = 5) -> dict[str, Any]:
    """Query Qdrant for similar past incidents (stub until Qdrant is seeded)."""
    return {"query": query, "similar_incidents": [], "status": "qdrant_not_seeded"}
