"""
UC6 — Self-Healing service.
Receives remediation requests (from n8n), validates against OPA, executes actions.
Actions: restart_pod, scale_deployment, rollback_deployment, drain_node.

Security invariant: FAIL-CLOSED — if OPA is unreachable, all remediations are BLOCKED.
This prevents autonomous remediation without a valid policy decision.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time

import httpx
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

try:
    # When src/ is on sys.path (unit tests, PYTHONPATH=src)
    from resilience import CircuitBreaker, CircuitBreakerOpenError, retry_call
except ImportError:  # When imported as the `src.main` package (container runtime)
    from src.resilience import CircuitBreaker, CircuitBreakerOpenError, retry_call

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
OPA_RETRIES = Counter(
    "self_healing_opa_retries_total",
    "Transient OPA call retries attempted before success or fail-closed",
)
OPA_CB_OPEN = Counter(
    "self_healing_opa_circuit_open_total",
    "Times the OPA circuit breaker fast-failed a request (fail-closed)",
)
IDEMPOTENT_HITS = Counter(
    "self_healing_idempotent_hits_total",
    "Remediation requests served from the idempotency cache (deduplicated)",
)

OPA_URL = os.getenv("OPA_URL", "http://opa:8181")
# Read the correctly-named env var; default TRUE so CI is always dry-run safe
DRY_RUN = os.getenv("SELF_HEALING_DRY_RUN", "true").lower() == "true"

# Resilience tunables — retry transient OPA faults before failing closed.
OPA_MAX_RETRIES = int(os.getenv("OPA_MAX_RETRIES", "3"))
OPA_RETRY_BASE_SECONDS = float(os.getenv("OPA_RETRY_BASE_SECONDS", "0.1"))
OPA_CB_FAILURE_THRESHOLD = int(os.getenv("OPA_CB_FAILURE_THRESHOLD", "5"))
OPA_CB_RESET_SECONDS = float(os.getenv("OPA_CB_RESET_SECONDS", "30"))

# Circuit breaker guards OPA so a sustained outage fast-fails (still fail-closed).
_opa_breaker = CircuitBreaker(
    failure_threshold=OPA_CB_FAILURE_THRESHOLD,
    reset_timeout=OPA_CB_RESET_SECONDS,
)

# Idempotency: dedupe identical remediation requests within a TTL window so a
# retrying caller (n8n, Alertmanager) can't trigger the same action twice.
IDEMPOTENCY_TTL_SECONDS = float(os.getenv("IDEMPOTENCY_TTL_SECONDS", "300"))
_idempotency_cache: dict[str, tuple[float, dict]] = {}
_idempotency_lock = threading.Lock()

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
    idempotency_key: str | None = None


def _compute_idempotency_key(req: RemediationRequest) -> str:
    """Stable key for a remediation intent (explicit key wins, else content hash)."""
    if req.idempotency_key:
        return req.idempotency_key
    payload = json.dumps(
        {"action": req.action, "target": req.target, "trigger": req.trigger},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _idempotency_get(key: str) -> dict | None:
    """Return a cached result if the key is present and not expired."""
    now = time.monotonic()
    with _idempotency_lock:
        entry = _idempotency_cache.get(key)
        if entry is None:
            return None
        expires_at, cached = entry
        if now >= expires_at:
            _idempotency_cache.pop(key, None)
            return None
        return cached


def _idempotency_put(key: str, result: dict) -> None:
    """Cache a result and opportunistically evict expired entries."""
    now = time.monotonic()
    with _idempotency_lock:
        _idempotency_cache[key] = (now + IDEMPOTENCY_TTL_SECONDS, result)
        expired = [k for k, (exp, _) in _idempotency_cache.items() if now >= exp]
        for k in expired:
            _idempotency_cache.pop(k, None)


class RemediationResult(BaseModel):
    allowed: bool
    action: str
    target: dict
    dry_run: bool
    opa_decision: dict
    executed: bool
    deny_reasons: list[str]
    opa_reachable: bool


def _opa_post(opa_input: dict) -> dict:
    """Single OPA HTTP call. Raises on transport errors and 4xx/5xx."""
    resp = httpx.post(
        f"{OPA_URL}/v1/data/platform/self_healing",
        json=opa_input,
        timeout=5.0,
    )
    resp.raise_for_status()  # Raises on 4xx/5xx — not silently allow
    return resp.json().get("result", {})


def _query_opa(opa_input: dict) -> dict:
    """
    Query OPA for a remediation decision.
    FAIL-CLOSED: raises HTTPException(503) if OPA is unreachable.
    Never returns allow=True when OPA cannot be contacted.

    Resilience: transient faults (timeouts, connection resets) are retried with
    exponential backoff + jitter, guarded by a circuit breaker. Once retries are
    exhausted or the circuit is open, the request fails CLOSED (HTTP 503).
    """

    def _attempt() -> dict:
        return _opa_breaker.call(lambda: _opa_post(opa_input))

    try:
        result = retry_call(
            _attempt,
            attempts=OPA_MAX_RETRIES,
            base_seconds=OPA_RETRY_BASE_SECONDS,
            retry_on=(httpx.TimeoutException, httpx.TransportError),
            on_retry=lambda attempt, exc: OPA_RETRIES.inc(),
        )
        OPA_UP.set(1)
        return result
    except CircuitBreakerOpenError as exc:
        OPA_UP.set(0)
        OPA_UNAVAILABLE.inc()
        OPA_CB_OPEN.inc()
        logger.error("OPA circuit open — blocking remediation (fail-closed): %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Policy engine circuit open — remediation blocked by fail-closed policy",
        ) from exc
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
        logger.error(
            "OPA returned HTTP %d — blocking remediation (fail-closed)", exc.response.status_code
        )
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
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action: {req.action}. Allowed: {sorted(ALLOWED_ACTIONS)}",
        )

    # Idempotency: if this exact remediation already executed within the TTL,
    # return the prior result instead of executing a duplicate action.
    idem_key = _compute_idempotency_key(req)
    cached = _idempotency_get(idem_key)
    if cached is not None:
        IDEMPOTENT_HITS.inc()
        logger.info("Idempotent hit for %s on %s — returning cached result", req.action, req.target)
        return RemediationResult(**cached)

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

    result = RemediationResult(
        allowed=allowed,
        action=req.action,
        target=req.target,
        dry_run=req.dry_run,
        opa_decision=opa_result,
        executed=executed,
        deny_reasons=deny_reasons,
        opa_reachable=True,
    )

    # Only real, executed actions are cached — dry-runs and denials stay re-evaluable.
    if executed and not req.dry_run:
        _idempotency_put(idem_key, result.model_dump())

    return result
