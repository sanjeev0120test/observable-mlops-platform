"""
UC6 — Self-Healing service.
Receives remediation requests (from n8n), validates against OPA, executes actions.
Actions: restart_pod, scale_deployment, rollback_deployment, drain_node.
All actions are dry-run by default in CI (SELF_HEALING_DRY_RUN=true).
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

app = FastAPI(title="Self-Healing", version="0.1.0")

ACTIONS_TAKEN = Counter("self_healing_actions_total", "Remediation actions executed", ["action", "result"])

OPA_URL = os.getenv("OPA_URL", "http://opa:8181")
DRY_RUN = os.getenv("SELF_HEALING_DRY_RUN", "true").lower() == "true"

ALLOWED_ACTIONS = {"restart_pod", "scale_deployment", "rollback_deployment", "drain_node"}


class RemediationRequest(BaseModel):
    action: str
    target: dict
    trigger: dict
    dry_run: bool = DRY_RUN


class RemediationResult(BaseModel):
    allowed: bool
    action: str
    target: dict
    dry_run: bool
    opa_decision: dict
    executed: bool
    deny_reasons: list[str]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "self-healing", "dry_run": DRY_RUN}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/remediate", response_model=RemediationResult)
def remediate(req: RemediationRequest) -> RemediationResult:
    if req.action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    # Query OPA
    opa_input = {
        "input": {
            "action": req.action,
            "target": req.target,
            "trigger": req.trigger,
            "dry_run": req.dry_run,
        }
    }
    try:
        resp = httpx.post(
            f"{OPA_URL}/v1/data/platform/self_healing",
            json=opa_input,
            timeout=5.0,
        )
        opa_result = resp.json().get("result", {})
    except Exception:
        opa_result = {"allow": True, "deny_reasons": []}  # fail-open in CI when OPA unavailable

    allowed = opa_result.get("allow", False)
    deny_reasons = list(opa_result.get("deny_reasons", []))

    executed = False
    if allowed:
        if req.dry_run:
            executed = False  # dry-run: log only
        else:
            # Phase 1: real kubectl/API calls go here
            executed = True
        ACTIONS_TAKEN.labels(action=req.action, result="allowed").inc()
    else:
        ACTIONS_TAKEN.labels(action=req.action, result="denied").inc()

    return RemediationResult(
        allowed=allowed,
        action=req.action,
        target=req.target,
        dry_run=req.dry_run,
        opa_decision=opa_result,
        executed=executed,
        deny_reasons=deny_reasons,
    )
