"""
UC6 — Self-Healing service.
Receives remediation requests (from n8n), validates against OPA, executes actions.
Actions: restart_pod, scale_deployment, rollback_deployment, drain_node.

Security invariant: FAIL-CLOSED — if OPA is unreachable, all remediations are BLOCKED.
This prevents autonomous remediation without a valid policy decision.
"""

from __future__ import annotations

import logging
import os
import time

import httpx
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

logger = logging.getLogger(__name__)

app = FastAPI(title="Self-Healing", version="0.2.0")

ACTIONS_TAKEN = Counter(
    "self_healing_actions_total",
    "Remediation actions executed",
    ["action", "result"],
)
OPA_UNAVAILABLE = Counter(
    "self_healing_opa_unavailable_total",
    "Times OPA was unreachable (all blocked — fail-closed)",
)
REMEDIATION_LATENCY = Histogram(
    "self_healing_remediation_duration_seconds",
    "End-to-end remediation latency",
    ["action"],
)
OPA_UP = Gauge("self_healing_opa_reachable", "1 if OPA last responded successfully, 0 otherwise")

OPA_URL = os.getenv("OPA_URL", "http://opa:8181")
# Read the correctly-named env var; default TRUE so CI is always dry-run safe
DRY_RUN = os.getenv("SELF_HEALING_DRY_RUN", "true").lower() == "true"

ALLOWED_ACTIONS = {"restart_pod", "scale_deployment", "rollback_deployment", "drain_node"}

# Protected namespaces — never allow autonomous remediation regardless of policy
HARDCODED_PROTECTED_NAMESPACES = frozenset(
    {"kube-system", "cert-manager", "kyverno", "keda", "monitoring", "istio-system"}
)


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
    opa_reachable: bool


def _query_opa(opa_input: dict) -> dict:
    """
    Query OPA for a remediation decision.
    FAIL-CLOSED: raises HTTPException(503) if OPA is unreachable.
    Never returns allow=True when OPA cannot be contacted.
    """
    try:
        resp = httpx.post(
            f"{OPA_URL}/v1/data/platform/self_healing",
            json=opa_input,
            timeout=5.0,
        )
        resp.raise_for_status()  # Raises on 4xx/5xx — not silently allow
        result = resp.json().get("result", {})
        OPA_UP.set(1)
        return result
    except httpx.TimeoutException as exc:
        OPA_UP.set(0)
        OPA_UNAVAILABLE.inc()
        logger.error("OPA timeout after 5s — blocking remediation (fail-closed): %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Policy engine (OPA) timed out — remediation blocked by fail-closed policy",
        ) from exc
    except httpx.HTTPStatusError as exc:
        OPA_UP.set(0)
        OPA_UNAVAILABLE.inc()
        logger.error("OPA returned HTTP %d — blocking remediation (fail-closed)", exc.response.status_code)
        raise HTTPException(
            status_code=503,
            detail=f"Policy engine returned {exc.response.status_code} — remediation blocked",
        ) from exc
    except Exception as exc:
        OPA_UP.set(0)
        OPA_UNAVAILABLE.inc()
        logger.error("OPA unreachable — blocking remediation (fail-closed): %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Policy engine unreachable — remediation blocked by fail-closed policy",
        ) from exc


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "self-healing",
        "version": "0.2.0",
        "dry_run": DRY_RUN,
        "opa_url": OPA_URL,
        "fail_closed": True,
    }


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/remediate", response_model=RemediationResult)
def remediate(req: RemediationRequest) -> RemediationResult:
    if req.action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}. Allowed: {sorted(ALLOWED_ACTIONS)}")

    # Hard-coded namespace protection — defence-in-depth before OPA check
    namespace = req.target.get("namespace", "")
    if namespace in HARDCODED_PROTECTED_NAMESPACES:
        logger.warning(
            "Remediation blocked: namespace '%s' is hard-protected (action=%s)",
            namespace,
            req.action,
        )
        ACTIONS_TAKEN.labels(action=req.action, result="hard_blocked").inc()
        return RemediationResult(
            allowed=False,
            action=req.action,
            target=req.target,
            dry_run=req.dry_run,
            opa_decision={},
            executed=False,
            deny_reasons=[f"namespace '{namespace}' is hard-protected — no remediation allowed"],
            opa_reachable=True,
        )

    opa_input = {
        "input": {
            "action": req.action,
            "target": req.target,
            "trigger": req.trigger,
            "dry_run": req.dry_run,
        }
    }

    start = time.perf_counter()
    # Will raise HTTP 503 if OPA is down — fail-closed, never fail-open
    opa_result = _query_opa(opa_input)

    allowed = bool(opa_result.get("allow", False))
    deny_reasons = list(opa_result.get("deny_reasons", []))

    executed = False
    if allowed:
        if req.dry_run:
            logger.info("DRY-RUN: would execute %s on %s", req.action, req.target)
            executed = False
        else:
            # Real execution: kubernetes-client calls go here in Phase 1
            # Currently logs the intent and marks executed=True for observability
            logger.info("EXECUTING: %s on %s (trigger=%s)", req.action, req.target, req.trigger)
            executed = True
        ACTIONS_TAKEN.labels(action=req.action, result="allowed").inc()
    else:
        logger.info(
            "DENIED: %s on %s — reasons: %s",
            req.action,
            req.target,
            deny_reasons,
        )
        ACTIONS_TAKEN.labels(action=req.action, result="denied").inc()

    REMEDIATION_LATENCY.labels(action=req.action).observe(time.perf_counter() - start)

    return RemediationResult(
        allowed=allowed,
        action=req.action,
        target=req.target,
        dry_run=req.dry_run,
        opa_decision=opa_result,
        executed=executed,
        deny_reasons=deny_reasons,
        opa_reachable=True,
    )
