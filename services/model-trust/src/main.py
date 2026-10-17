"""
Model Trust Score service.

Endpoints:
  POST /api/v1/score                      — score a model version, append to ledger, advise
  POST /api/v1/score/from-evidence        — same, but signals are assembled from raw evidence
  GET  /api/v1/models/{name}/history      — ledger history for one model
  GET  /api/v1/ledger/verify              — walk the hash chain
  GET  /api/v1/ledger/attestation         — regulator-facing attestation document
  GET  /api/v1/bands                      — band thresholds + meanings
  GET  /                               — operator console
  GET  /health, /metrics
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from pydantic import BaseModel, Field

try:
    # When src/ is on sys.path (unit tests, PYTHONPATH=src)
    from assemble import assemble_signals
    from trust_engine import (
        BANDS,
        ENGINE_VERSION,
        PILLAR_WEIGHTS,
        TrustLedger,
        compute_trust_score,
        default_ledger_path,
    )
except ImportError:  # pragma: no cover — container runs `uvicorn src.main:app`
    from .assemble import assemble_signals
    from .trust_engine import (
        BANDS,
        ENGINE_VERSION,
        PILLAR_WEIGHTS,
        TrustLedger,
        compute_trust_score,
        default_ledger_path,
    )

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("model-trust")

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "")
MLFLOW_WRITEBACK = os.getenv("MLFLOW_WRITEBACK", "true").lower() == "true"

TRUST_SCORE = Gauge(
    "model_trust_score", "Model Trust Score (300-1000)", ["model", "version", "band"]
)
PILLAR_HEALTH = Gauge(
    "model_trust_pillar_health", "Per-pillar health (0-1)", ["model", "version", "pillar"]
)
SCORES_TOTAL = Counter("model_trust_scores_total", "Scoring events", ["band"])
LEDGER_ENTRIES = Gauge("model_trust_ledger_entries", "Entries in the trust ledger")
LEDGER_OK = Gauge("model_trust_ledger_integrity_ok", "1 if the hash chain verifies, else 0")
REGRESSIONS = Counter(
    "model_trust_regressions_total",
    "Recorded scores that fell a band or at least 50 points",
    ["model"],
)
# A 50-point drop is one band boundary wide (SUBPRIME/FAIR/GOOD are 100 apart,
# PRIME starts 150 above GOOD). Smaller noise should not page anyone.
REGRESSION_POINTS = 50
_BAND_RANK = {band: rank for rank, (_, band, _) in enumerate(reversed(BANDS))}
MLFLOW_WRITEBACKS = Counter(
    "model_trust_mlflow_writebacks_total", "MLflow tag write-backs", ["status"]
)

app = FastAPI(
    title="Model Trust Score",
    version=ENGINE_VERSION,
    description="FICO-style trust score for ML model versions with a tamper-evident ledger",
)
ledger = TrustLedger(default_ledger_path())
_CONSOLE_HTML = Path(__file__).with_name("console.html")


class ScoreRequest(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=128)
    model_version: str = Field(..., min_length=1, max_length=64)
    signals: dict[str, Any] = Field(default_factory=dict)
    targets: dict[str, float] = Field(default_factory=dict)
    target_band: str = Field("GOOD", pattern="^(PRIME|GOOD|FAIR|SUBPRIME)$")
    record: bool = True


class EvidenceRequest(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=128)
    model_version: str = Field(..., min_length=1, max_length=64)
    evidence: dict[str, Any] = Field(default_factory=dict)
    targets: dict[str, float] = Field(default_factory=dict)
    target_band: str = Field("GOOD", pattern="^(PRIME|GOOD|FAIR|SUBPRIME)$")
    record: bool = True


def _writeback_to_mlflow(model_name: str, version: str, score: int, band: str) -> None:
    """Attach the score to the MLflow 3 model version so it is visible in the registry UI."""
    if not (MLFLOW_WRITEBACK and MLFLOW_TRACKING_URI):
        return
    try:
        import mlflow

        client = mlflow.MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)
        client.set_model_version_tag(model_name, version, "trust_score", str(score))
        client.set_model_version_tag(model_name, version, "trust_band", band)
        MLFLOW_WRITEBACKS.labels(status="ok").inc()
    except Exception as exc:  # noqa: BLE001 — write-back is best-effort
        MLFLOW_WRITEBACKS.labels(status="error").inc()
        logger.warning("MLflow write-back skipped for %s v%s: %s", model_name, version, exc)


def _regression(
    score: int,
    band: str,
    previous: int | None,
    previous_band: str | None,
) -> dict[str, Any] | None:
    """Flag a drop that is large enough to change an on-call decision."""
    if previous is None or previous_band is None:
        return None
    delta = score - previous
    dropped = _BAND_RANK[band] < _BAND_RANK[previous_band]
    if delta > -REGRESSION_POINTS and not dropped:
        return None
    return {"delta": delta, "previous_band": previous_band, "band_dropped": dropped}


def _refresh_ledger_metrics() -> None:
    v = ledger.verify()
    LEDGER_ENTRIES.set(v.entries)
    LEDGER_OK.set(1 if v.ok else 0)


@app.get("/", response_class=HTMLResponse)
def console() -> HTMLResponse:
    """Operator page: score a version from the evidence the service actually accepts."""
    if not _CONSOLE_HTML.exists():
        raise HTTPException(status_code=404, detail="console.html is not installed")
    return HTMLResponse(_CONSOLE_HTML.read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict[str, Any]:
    v = ledger.verify()
    return {
        "status": "ok" if v.ok else "degraded",
        "engine_version": ENGINE_VERSION,
        "ledger_entries": v.entries,
        "ledger_integrity_ok": v.ok,
        "mlflow_writeback": bool(MLFLOW_WRITEBACK and MLFLOW_TRACKING_URI),
    }


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    _refresh_ledger_metrics()
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/bands")
def bands() -> dict[str, Any]:
    return {
        "bands": [{"min_score": t, "band": b, "meaning": m} for t, b, m in BANDS],
        "pillar_weights": PILLAR_WEIGHTS,
        "engine_version": ENGINE_VERSION,
    }


@app.post("/api/v1/score")
def score(req: ScoreRequest) -> dict[str, Any]:
    try:
        report = compute_trust_score(
            req.model_name, req.model_version, req.signals, req.targets, req.target_band
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    history = ledger.history(req.model_name)
    previous = history[-1]["score"] if history else None
    previous_band = history[-1]["band"] if history else None
    entry = ledger.append(report) if req.record else None
    regression = _regression(report.score, report.band, previous, previous_band)
    if regression is not None and req.record:
        REGRESSIONS.labels(req.model_name).inc()

    TRUST_SCORE.labels(req.model_name, req.model_version, report.band).set(report.score)
    for p in report.pillars:
        PILLAR_HEALTH.labels(req.model_name, req.model_version, p.pillar).set(p.health)
    SCORES_TOTAL.labels(report.band).inc()
    _refresh_ledger_metrics()

    if req.record:
        _writeback_to_mlflow(req.model_name, req.model_version, report.score, report.band)

    body = report.to_dict()
    body["previous_score"] = previous
    body["score_delta"] = (report.score - previous) if previous is not None else None
    body["ledger_entry"] = entry
    body["signals_used"] = dict(req.signals)
    body["regression"] = regression
    return body


@app.post("/api/v1/score/from-evidence")
def score_from_evidence(req: EvidenceRequest) -> dict[str, Any]:
    """Score from raw platform evidence. Missing sources stay unobserved."""
    try:
        signals = assemble_signals(req.evidence)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    body = score(
        ScoreRequest(
            model_name=req.model_name,
            model_version=req.model_version,
            signals=signals,
            targets=req.targets,
            target_band=req.target_band,
            record=req.record,
        )
    )
    return body


@app.get("/api/v1/models/{model_name}/history")
def history(model_name: str) -> dict[str, Any]:
    hist = ledger.history(model_name)
    if not hist:
        raise HTTPException(status_code=404, detail=f"No ledger entries for {model_name!r}")
    return {"model_name": model_name, "entries": hist, "latest": hist[-1]}


@app.get("/api/v1/ledger/verify")
def verify() -> dict[str, Any]:
    v = ledger.verify()
    _refresh_ledger_metrics()
    return {
        "ok": v.ok,
        "entries": v.entries,
        "head_hash": v.head_hash,
        "first_bad_seq": v.first_bad_seq,
        "reason": v.reason,
    }


@app.get("/api/v1/ledger/attestation")
def attestation() -> dict[str, Any]:
    return ledger.attestation()
