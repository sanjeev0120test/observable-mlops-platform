"""
Model Trust Score — a FICO-style credit score for deployed ML models.

Why this exists
---------------
Every monitoring product on the market reports signals in silos: a drift dashboard here,
an SLO burn-rate there, a CVE list in a third tool, an explainability report in MLflow.
Nobody answers the question an on-call engineer, a product owner and an auditor all ask:

    "Can I trust *this* model version in production right now — and if not, what is the
     single cheapest thing I can do about it?"

The Trust Score answers it with three properties no existing tool combines:

1. **One number, fully decomposable.** Six pillars (drift, performance, reliability, cost,
   security, governance) roll up into a 300–1000 score. Every point is attributable to a
   pillar and to a concrete signal — nothing is a black box.
2. **Counterfactual remediation advisor.** For each lost point we know which action
   recovers it and roughly how long that action takes, so the advisor returns a
   points-per-hour ranked plan and the minimal set of actions to reach a target band.
3. **Tamper-evident ledger.** Every score is appended to a SHA-256 hash-chained ledger.
   Change one historic entry and verification fails at that sequence number. This is the
   record-keeping evidence EU AI Act Art. 12 asks for, produced as a by-product of
   operating the platform instead of as a quarterly spreadsheet.

Pure Python, no I/O except the ledger file, fully deterministic — safe to call from CI,
from the FastAPI service, from an Airflow DAG or from an OPA sidecar.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_VERSION = "1.0.0"

SCORE_FLOOR = 300
SCORE_CEILING = 1000
SCORE_RANGE = SCORE_CEILING - SCORE_FLOOR

# Pillar weights sum to 1.0. Performance and drift dominate because they are the leading
# indicators of a model silently going wrong; cost is lowest because it is rarely urgent.
PILLAR_WEIGHTS: dict[str, float] = {
    "performance": 0.25,
    "drift": 0.20,
    "reliability": 0.20,
    "security": 0.15,
    "governance": 0.10,
    "cost": 0.10,
}

# Health assigned to a pillar for which *no* signal was supplied. Deliberately below the
# "Fair" threshold: you do not get credit for what you do not measure.
UNOBSERVED_HEALTH = 0.40

BANDS: list[tuple[int, str, str]] = [
    (850, "PRIME", "Auto-promotion eligible; no human gate required"),
    (700, "GOOD", "Promotable with reviewer sign-off"),
    (600, "FAIR", "Shadow / canary traffic only"),
    (SCORE_FLOOR, "SUBPRIME", "Blocked from production; rollback candidate"),
]

# Default production targets. Callers override per model via the `targets` argument.
DEFAULT_TARGETS: dict[str, float] = {
    "performance_baseline": 0.80,  # accuracy / f1 the model was approved at
    "latency_slo_ms": 500.0,
    "cost_budget_per_1k_usd": 0.05,
}


# --------------------------------------------------------------------------------------
# Remediation catalogue: (pillar, action, effort_hours, fraction of lost points recovered)
# Effort numbers are planning-grade estimates for a team that already runs this platform.
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Remediation:
    pillar: str
    action: str
    effort_hours: float
    recovery_fraction: float
    automation: str  # which platform capability executes it

    def points_recoverable(self, points_lost: float) -> float:
        return round(points_lost * self.recovery_fraction, 1)


REMEDIATIONS: list[Remediation] = [
    Remediation(
        "drift",
        "Trigger retraining on the last 7 days (Airflow pod_failure_prediction_retrain)",
        2.0,
        0.85,
        "UC1 drift gate -> Airflow DAG",
    ),
    Remediation(
        "drift",
        "Refresh reference window to post-deployment baseline",
        0.5,
        0.40,
        "drift-monitor /api/v1/reference",
    ),
    Remediation(
        "performance",
        "Promote the champion/challenger that won shadow evaluation",
        1.0,
        0.80,
        "UC22 shadow_evaluator PromotionGate",
    ),
    Remediation(
        "performance",
        "Run Optuna HPO sweep and register best trial",
        6.0,
        0.90,
        "UC14 HPO workflow",
    ),
    Remediation(
        "reliability",
        "Scale replicas ahead of forecast load (KEDA ScaledObject)",
        0.5,
        0.60,
        "UC4 predictive-scaler",
    ),
    Remediation(
        "reliability",
        "Enable request hedging + circuit breaker on inference path",
        4.0,
        0.80,
        "services/self-healing resilience.py",
    ),
    Remediation(
        "cost",
        "Right-size inference pods to observed p95 CPU/memory",
        1.0,
        0.70,
        "UC10 cost-optimizer recommendations",
    ),
    Remediation(
        "cost",
        "Move batch inference to spot/preemptible node pool",
        3.0,
        0.50,
        "Karpenter NodePool",
    ),
    Remediation(
        "security",
        "Rebuild image on patched base and re-sign (Cosign)",
        1.5,
        0.90,
        "workflow 28-sbom-signing",
    ),
    Remediation(
        "security",
        "Fix Kyverno / OPA policy violations in deployment manifest",
        1.0,
        0.80,
        "UC7 / UC12 policy gates",
    ),
    Remediation(
        "governance",
        "Log SHAP global + local explanations to the model version",
        1.0,
        0.45,
        "UC17 explainability workflow",
    ),
    Remediation(
        "governance",
        "Publish model card and OpenLineage lineage for the version",
        2.0,
        0.55,
        "MLflow model version tags + OpenLineage",
    ),
]


# --------------------------------------------------------------------------------------
# Knockout caps. Like a bankruptcy on a credit file: some findings bound the score no
# matter how good everything else looks. Without these, a 93%-accurate model shipped in an
# unsigned image with critical CVEs would average out to "PRIME" — the exact blind spot of
# accuracy-only monitoring. Each cap names the pillar and the action that lifts it.
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Cap:
    rule: str
    cap: int
    pillar: str
    lifting_action: str  # must match a Remediation.action in REMEDIATIONS


def _active_caps(s: dict[str, Any]) -> list[Cap]:
    caps: list[Cap] = []
    crit = _as_float(s.get("critical_cves"))
    if crit is not None and crit >= 3:
        caps.append(
            Cap(
                "critical_cves>=3",
                band_threshold("FAIR") - 1,
                "security",
                "Rebuild image on patched base and re-sign (Cosign)",
            )
        )
    elif crit is not None and crit >= 1:
        caps.append(
            Cap(
                "critical_cves>=1",
                band_threshold("GOOD") - 1,
                "security",
                "Rebuild image on patched base and re-sign (Cosign)",
            )
        )
    signed = _as_bool(s.get("image_signed"))
    if signed is False:
        caps.append(
            Cap(
                "image_unsigned",
                band_threshold("PRIME") - 1,
                "security",
                "Rebuild image on patched base and re-sign (Cosign)",
            )
        )
    viol = _as_float(s.get("policy_violations"))
    if viol is not None and viol >= 1:
        caps.append(
            Cap(
                "policy_violations>=1",
                band_threshold("GOOD") - 1,
                "security",
                "Fix Kyverno / OPA policy violations in deployment manifest",
            )
        )
    drop = _as_float(s.get("estimated_performance_drop"))
    if drop is not None and drop >= 0.20:
        caps.append(
            Cap(
                "performance_drop>=0.20",
                band_threshold("FAIR") - 1,
                "performance",
                "Promote the champion/challenger that won shadow evaluation",
            )
        )
    ebr = _as_float(s.get("error_budget_remaining"))
    if ebr is not None and ebr <= 0.0:
        caps.append(
            Cap(
                "error_budget_exhausted",
                band_threshold("GOOD") - 1,
                "reliability",
                "Enable request hedging + circuit breaker on inference path",
            )
        )
    eu = _as_bool(s.get("eu_ai_act_compliant"))
    if eu is False:
        caps.append(
            Cap(
                "eu_ai_act_non_compliant",
                band_threshold("PRIME") - 1,
                "governance",
                "Publish model card and OpenLineage lineage for the version",
            )
        )
    return caps


# --------------------------------------------------------------------------------------
# Signal -> health (0..1) transforms. All are monotone and clamp to [0, 1].
# --------------------------------------------------------------------------------------
def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _lower_better(value: float, full_credit_at: float, zero_credit_at: float) -> float:
    if value <= full_credit_at:
        return 1.0
    if value >= zero_credit_at:
        return 0.0
    return _clamp01(1.0 - (value - full_credit_at) / (zero_credit_at - full_credit_at))


def _higher_better(value: float, zero_credit_at: float, full_credit_at: float) -> float:
    if value >= full_credit_at:
        return 1.0
    if value <= zero_credit_at:
        return 0.0
    return _clamp01((value - zero_credit_at) / (full_credit_at - zero_credit_at))


def _as_float(v: Any) -> float | None:
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"true", "1", "yes", "y"}
    return None


def _pillar_drift(s: dict[str, Any], _t: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    if (psi := _as_float(s.get("psi_score"))) is not None:
        out["psi_score"] = _lower_better(psi, 0.10, 0.50)
    if (ks := _as_float(s.get("ks_statistic"))) is not None:
        out["ks_statistic"] = _lower_better(ks, 0.10, 0.40)
    if (n := _as_float(s.get("drifted_feature_count"))) is not None:
        out["drifted_feature_count"] = _lower_better(n, 0, 5)
    return out


def _pillar_performance(s: dict[str, Any], t: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    base = t["performance_baseline"]
    for key in ("accuracy", "f1_score", "roc_auc"):
        if (v := _as_float(s.get(key))) is not None:
            # Full credit at baseline, zero credit at 25 points below baseline.
            out[key] = _higher_better(v, base - 0.25, base)
    if (drop := _as_float(s.get("estimated_performance_drop"))) is not None:
        out["estimated_performance_drop"] = _lower_better(drop, 0.02, 0.20)
    return out


def _pillar_reliability(s: dict[str, Any], t: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    if (ebr := _as_float(s.get("error_budget_remaining"))) is not None:
        out["error_budget_remaining"] = _higher_better(ebr, 0.0, 0.5)
    if (p99 := _as_float(s.get("p99_latency_ms"))) is not None:
        slo = t["latency_slo_ms"]
        out["p99_latency_ms"] = _lower_better(p99, slo, slo * 2)
    if (avail := _as_float(s.get("availability_30d"))) is not None:
        out["availability_30d"] = _higher_better(avail, 0.99, 0.999)
    return out


def _pillar_cost(s: dict[str, Any], t: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    if (c := _as_float(s.get("cost_per_1k_predictions_usd"))) is not None:
        budget = t["cost_budget_per_1k_usd"]
        out["cost_per_1k_predictions_usd"] = _lower_better(c, budget, budget * 3)
    if (idle := _as_float(s.get("idle_capacity_ratio"))) is not None:
        out["idle_capacity_ratio"] = _lower_better(idle, 0.20, 0.70)
    return out


def _pillar_security(s: dict[str, Any], _t: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    if (crit := _as_float(s.get("critical_cves"))) is not None:
        out["critical_cves"] = _clamp01(1.0 - 0.40 * crit)
    if (high := _as_float(s.get("high_cves"))) is not None:
        out["high_cves"] = _clamp01(1.0 - 0.10 * high)
    if (viol := _as_float(s.get("policy_violations"))) is not None:
        out["policy_violations"] = _clamp01(1.0 - 0.25 * viol)
    if (signed := _as_bool(s.get("image_signed"))) is not None:
        out["image_signed"] = 1.0 if signed else 0.0
    return out


_GOVERNANCE_FLAGS = (
    "shap_logged",
    "model_card_present",
    "lineage_recorded",
    "eu_ai_act_compliant",
    "human_oversight_defined",
)


def _pillar_governance(s: dict[str, Any], _t: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _GOVERNANCE_FLAGS:
        if (b := _as_bool(s.get(key))) is not None:
            out[key] = 1.0 if b else 0.0
    return out


_PILLAR_FUNCS = {
    "drift": _pillar_drift,
    "performance": _pillar_performance,
    "reliability": _pillar_reliability,
    "cost": _pillar_cost,
    "security": _pillar_security,
    "governance": _pillar_governance,
}


# --------------------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------------------
@dataclass
class PillarResult:
    pillar: str
    weight: float
    health: float  # 0..1
    points_available: float
    points_earned: float
    points_lost: float
    observed: bool
    signals: dict[str, float] = field(default_factory=dict)  # signal -> health contribution


@dataclass
class RemediationPlan:
    pillar: str
    action: str
    effort_hours: float
    points_recoverable: float
    points_per_hour: float
    automation: str
    lifts_cap: bool = False
    # True when a knockout cap is binding and this action does NOT lift it: its points are
    # real but cannot materialise until the cap is lifted first.
    blocked_by_cap: bool = False


@dataclass
class TrustReport:
    model_name: str
    model_version: str
    score: int
    band: str
    band_meaning: str
    score_uncapped: int
    caps_applied: list[dict[str, Any]]
    pillars: list[PillarResult]
    recommendations: list[RemediationPlan]
    target_band: str
    plan_to_target: list[RemediationPlan]
    plan_to_target_hours: float
    plan_reaches_target: bool
    inputs_hash: str
    engine_version: str = ENGINE_VERSION
    computed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------
def band_for(score: int) -> tuple[str, str]:
    for threshold, name, meaning in BANDS:
        if score >= threshold:
            return name, meaning
    return BANDS[-1][1], BANDS[-1][2]


def band_threshold(band: str) -> int:
    for threshold, name, _ in BANDS:
        if name == band:
            return threshold
    raise ValueError(f"Unknown band {band!r}; valid: {[b[1] for b in BANDS]}")


def canonical_hash(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_trust_score(
    model_name: str,
    model_version: str,
    signals: dict[str, Any],
    targets: dict[str, float] | None = None,
    target_band: str = "GOOD",
    now: datetime | None = None,
) -> TrustReport:
    """Score one model version. Deterministic for identical inputs."""
    if not model_name:
        raise ValueError("model_name is required")
    band_threshold(target_band)  # validates
    t = {**DEFAULT_TARGETS, **(targets or {})}
    signals = signals or {}

    pillars: list[PillarResult] = []
    weighted_health = 0.0
    for name, weight in PILLAR_WEIGHTS.items():
        contributions = _PILLAR_FUNCS[name](signals, t)
        observed = bool(contributions)
        health = sum(contributions.values()) / len(contributions) if observed else UNOBSERVED_HEALTH
        available = SCORE_RANGE * weight
        earned = available * health
        pillars.append(
            PillarResult(
                pillar=name,
                weight=weight,
                health=round(health, 4),
                points_available=round(available, 1),
                points_earned=round(earned, 1),
                points_lost=round(available - earned, 1),
                observed=observed,
                signals={k: round(v, 4) for k, v in contributions.items()},
            )
        )
        weighted_health += weight * health

    score_uncapped = int(round(SCORE_FLOOR + SCORE_RANGE * weighted_health))
    caps = _active_caps(signals)
    score = min([score_uncapped, *(c.cap for c in caps)])
    band, meaning = band_for(score)
    binding = [c for c in caps if c.cap < score_uncapped]

    recommendations = _advise(pillars, binding, score, score_uncapped)
    plan, plan_hours, reaches = _plan_to_band(score, target_band, recommendations)

    ts = (now or datetime.now(timezone.utc)).isoformat()
    return TrustReport(
        model_name=model_name,
        model_version=str(model_version),
        score=score,
        band=band,
        band_meaning=meaning,
        score_uncapped=score_uncapped,
        caps_applied=[
            {"rule": c.rule, "cap": c.cap, "pillar": c.pillar, "binding": c in binding}
            for c in caps
        ],
        pillars=pillars,
        recommendations=recommendations,
        target_band=target_band,
        plan_to_target=plan,
        plan_to_target_hours=round(plan_hours, 1),
        plan_reaches_target=reaches,
        inputs_hash=canonical_hash({"signals": signals, "targets": t}),
        computed_at=ts,
    )


def _advise(
    pillars: list[PillarResult],
    binding_caps: list[Cap],
    score: int,
    score_uncapped: int,
) -> list[RemediationPlan]:
    lost = {p.pillar: p.points_lost for p in pillars}
    by_action = {r.action: r for r in REMEDIATIONS}

    # Points released when a given cap is lifted = how far the score can rise before the
    # next-tightest remaining cap (or the uncapped score) binds.
    cap_bonus: dict[str, float] = {}
    for c in binding_caps:
        others = [
            o.cap for o in binding_caps if o is not c and o.lifting_action != c.lifting_action
        ]
        ceiling = min([score_uncapped, *others])
        cap_bonus[c.lifting_action] = cap_bonus.get(c.lifting_action, 0.0) + max(
            0.0, ceiling - score
        )

    plans: list[RemediationPlan] = []
    for r in REMEDIATIONS:
        pts = r.points_recoverable(lost.get(r.pillar, 0.0)) + cap_bonus.get(r.action, 0.0)
        pts = round(pts, 1)
        if pts < 1.0:
            continue
        lifts = r.action in cap_bonus
        plans.append(
            RemediationPlan(
                pillar=r.pillar,
                action=f"[LIFTS CAP] {r.action}" if lifts else r.action,
                effort_hours=r.effort_hours,
                points_recoverable=pts,
                points_per_hour=round(pts / r.effort_hours, 1),
                automation=by_action[r.action].automation,
                lifts_cap=lifts,
                blocked_by_cap=bool(binding_caps) and not lifts,
            )
        )
    # While a cap binds, nothing else can move the score: cap lifts always come first,
    # then everything by ROI.
    plans.sort(key=lambda p: (not p.lifts_cap, -p.points_per_hour, -p.points_recoverable, p.action))
    return plans


def _plan_to_band(
    score: int, target_band: str, ranked: list[RemediationPlan]
) -> tuple[list[RemediationPlan], float, bool]:
    """Greedy by ROI, at most one action per pillar (recoveries within a pillar overlap)."""
    needed = band_threshold(target_band) - score
    if needed <= 0:
        return [], 0.0, True
    chosen: list[RemediationPlan] = []
    used_pillars: set[str] = set()
    gained = 0.0
    hours = 0.0
    for p in ranked:
        if p.pillar in used_pillars:
            continue
        chosen.append(p)
        used_pillars.add(p.pillar)
        gained += p.points_recoverable
        hours += p.effort_hours
        if gained >= needed:
            return chosen, hours, True
    return chosen, hours, False


# --------------------------------------------------------------------------------------
# Tamper-evident ledger
# --------------------------------------------------------------------------------------
GENESIS_HASH = "0" * 64


@dataclass
class LedgerVerification:
    ok: bool
    entries: int
    head_hash: str
    first_bad_seq: int | None = None
    reason: str | None = None


class TrustLedger:
    """Append-only JSONL with a SHA-256 hash chain. One line per scoring event."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # -- internal -----------------------------------------------------------------
    def _read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    @staticmethod
    def entry_hash(entry: dict[str, Any]) -> str:
        body = {k: v for k, v in entry.items() if k != "hash"}
        return canonical_hash(body)

    # -- public -------------------------------------------------------------------
    def append(self, report: TrustReport) -> dict[str, Any]:
        with self._lock:
            entries = self._read_all()
            prev_hash = entries[-1]["hash"] if entries else GENESIS_HASH
            seq = len(entries) + 1
            entry: dict[str, Any] = {
                "seq": seq,
                "recorded_at": report.computed_at,
                "model_name": report.model_name,
                "model_version": report.model_version,
                "score": report.score,
                "band": report.band,
                "pillar_health": {p.pillar: p.health for p in report.pillars},
                "inputs_hash": report.inputs_hash,
                "engine_version": report.engine_version,
                "prev_hash": prev_hash,
            }
            entry["hash"] = self.entry_hash(entry)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
            return entry

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read_all()

    def history(self, model_name: str) -> list[dict[str, Any]]:
        return [e for e in self.entries() if e["model_name"] == model_name]

    def previous_score(self, model_name: str, before_seq: int | None = None) -> int | None:
        hist = self.history(model_name)
        if before_seq is not None:
            hist = [e for e in hist if e["seq"] < before_seq]
        return hist[-1]["score"] if hist else None

    def verify(self) -> LedgerVerification:
        entries = self.entries()
        prev = GENESIS_HASH
        for idx, e in enumerate(entries, start=1):
            if e.get("seq") != idx:
                return LedgerVerification(False, len(entries), "", idx, "sequence gap or reorder")
            if e.get("prev_hash") != prev:
                return LedgerVerification(False, len(entries), "", idx, "prev_hash mismatch")
            if self.entry_hash(e) != e.get("hash"):
                return LedgerVerification(False, len(entries), "", idx, "entry hash mismatch")
            prev = e["hash"]
        return LedgerVerification(True, len(entries), prev if entries else GENESIS_HASH)

    def attestation(self) -> dict[str, Any]:
        """Regulator-facing summary: enough to independently re-verify the chain."""
        v = self.verify()
        entries = self.entries()
        models = sorted({e["model_name"] for e in entries})
        return {
            "ledger_path": str(self.path),
            "entries": v.entries,
            "integrity_ok": v.ok,
            "first_bad_seq": v.first_bad_seq,
            "head_hash": v.head_hash,
            "genesis_hash": GENESIS_HASH,
            "hash_algorithm": "sha256(canonical_json(entry - hash))",
            "models_covered": models,
            "latest_by_model": {
                m: next(e for e in reversed(entries) if e["model_name"] == m) for m in models
            },
            "engine_version": ENGINE_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


def default_ledger_path() -> Path:
    return Path(os.getenv("TRUST_LEDGER_PATH", "/app/data/trust_ledger.jsonl"))
