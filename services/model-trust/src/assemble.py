"""
Turn heterogeneous platform evidence into Model Trust Score signals.

Monitoring products emit different shapes: MLflow metrics and tags, a Trivy JSON
report, a Kyverno policy report, an EU AI Act compliance report. The scorer only
understands a flat signal dict. This module is the adapter, and it has one rule
that matters: a signal is emitted only when something actually observed it.
Missing evidence stays missing, so the scorer treats the pillar as unobserved
instead of awarding credit for a scan that never ran.
"""

from __future__ import annotations

from typing import Any

# Metric name as the engine expects it -> aliases accepted from MLflow / drift jobs.
_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "psi_score": ("psi_score", "drift_psi", "psi"),
    "ks_statistic": ("ks_statistic", "ks_stat", "ks"),
    "drifted_feature_count": ("drifted_feature_count", "n_drifted_features"),
    "accuracy": ("accuracy", "val_accuracy"),
    "f1_score": ("f1_score", "f1", "val_f1"),
    "roc_auc": ("roc_auc", "auc", "val_roc_auc"),
    "estimated_performance_drop": ("estimated_performance_drop", "performance_drop"),
    "error_budget_remaining": ("error_budget_remaining", "error_budget_ratio"),
    "p99_latency_ms": ("p99_latency_ms", "latency_p99_ms"),
    "availability_30d": ("availability_30d", "availability"),
    "cost_per_1k_predictions_usd": ("cost_per_1k_predictions_usd", "cost_per_1k"),
    "idle_capacity_ratio": ("idle_capacity_ratio", "idle_ratio"),
}

# EU AI Act compliance-check names -> governance signals.
_CHECK_TO_SIGNAL = {
    "explainability_logged": "shap_logged",
    "model_card_exists": "model_card_present",
    "training_data_documented": "lineage_recorded",
    "human_oversight_gate": "human_oversight_defined",
}

_TRUE = {"true", "1", "yes", "y"}
_FALSE = {"false", "0", "no", "n"}


class EvidenceError(ValueError):
    """Evidence payload is not a shape the assembler can read."""


def assemble_signals(evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Flatten one evidence bundle into scorer signals.

    Later, more specific sources win over earlier ones, and an explicit
    ``evidence["signals"]`` dict wins over everything: the caller observed it
    directly.
    """
    if evidence is None:
        return {}
    if not isinstance(evidence, dict):
        raise EvidenceError("evidence must be a JSON object")

    metrics = _obj(evidence.get("metrics"), "metrics")
    tags = _obj(evidence.get("tags"), "tags")
    security = _obj(evidence.get("security"), "security")
    compliance = _obj(evidence.get("compliance"), "compliance")
    explicit = _obj(evidence.get("signals"), "signals")

    out: dict[str, Any] = {}
    _from_metrics_and_tags(out, metrics, tags)
    _from_security(out, security)
    _from_compliance(out, compliance)
    _from_top_level_flags(out, evidence)

    for key, value in explicit.items():
        if value is not None:
            out[key] = value
    return out


def _obj(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise EvidenceError(f"evidence.{name} must be a JSON object")
    return value


def _from_metrics_and_tags(out: dict[str, Any], metrics: dict, tags: dict) -> None:
    for canonical, aliases in _METRIC_ALIASES.items():
        value = _first_number(metrics, aliases)
        if value is None:
            value = _first_number(tags, aliases)
        if value is not None:
            out[canonical] = value

    shap = _explicit_bool(tags, "shap_values_logged", "shap_logged")
    if shap is None and _first_number(metrics, ("shap_mean_abs_impact",)) is not None:
        shap = True
    if shap is not None:
        out["shap_logged"] = shap

    if _has_text(tags, "training_dataset", "data_source", "openlineage_run_id"):
        out["lineage_recorded"] = True

    oversight = _explicit_bool(tags, "human_review_approved", "approval_gate_passed")
    if oversight is not None:
        out["human_oversight_defined"] = oversight

    card = _explicit_bool(tags, "model_card_present")
    if card is not None:
        out["model_card_present"] = card

    eu = _explicit_bool(tags, "eu_ai_act_compliant")
    if eu is not None:
        out["eu_ai_act_compliant"] = eu


def _from_security(out: dict[str, Any], security: dict) -> None:
    trivy = security.get("trivy")
    if isinstance(trivy, dict):
        crit, high = _count_trivy(trivy)
        out["critical_cves"] = crit
        out["high_cves"] = high

    kyverno = security.get("kyverno")
    if isinstance(kyverno, dict):
        out["policy_violations"] = _count_kyverno_failures(kyverno)

    for key in ("critical_cves", "high_cves", "policy_violations"):
        if key in security and security[key] is not None:
            number = _as_number(security[key])
            if number is None:
                raise EvidenceError(f"evidence.security.{key} must be a number")
            out[key] = number

    if "image_signed" in security and security["image_signed"] is not None:
        signed = _as_bool(security["image_signed"])
        if signed is None:
            raise EvidenceError("evidence.security.image_signed must be a boolean")
        out["image_signed"] = signed
    else:
        cosign = security.get("cosign")
        if isinstance(cosign, dict) and "verified" in cosign:
            verified = _as_bool(cosign.get("verified"))
            if verified is None:
                raise EvidenceError("evidence.security.cosign.verified must be a boolean")
            out["image_signed"] = verified


def _from_compliance(out: dict[str, Any], compliance: dict) -> None:
    if "is_compliant" in compliance and compliance["is_compliant"] is not None:
        flag = _as_bool(compliance["is_compliant"])
        if flag is None:
            raise EvidenceError("evidence.compliance.is_compliant must be a boolean")
        out["eu_ai_act_compliant"] = flag

    checks = compliance.get("checks") or []
    if not isinstance(checks, list):
        raise EvidenceError("evidence.compliance.checks must be a list")
    for check in checks:
        if not isinstance(check, dict):
            continue
        signal = _CHECK_TO_SIGNAL.get(str(check.get("name", "")))
        if signal is None or "passed" not in check:
            continue
        passed = _as_bool(check.get("passed"))
        if passed is None:
            raise EvidenceError(
                f"compliance check {check.get('name')!r} has a non-boolean 'passed'"
            )
        out[signal] = passed


def _from_top_level_flags(out: dict[str, Any], evidence: dict) -> None:
    if "model_card_present" in evidence and evidence["model_card_present"] is not None:
        flag = _as_bool(evidence["model_card_present"])
        if flag is None:
            raise EvidenceError("evidence.model_card_present must be a boolean")
        out["model_card_present"] = flag


def _count_trivy(doc: dict) -> tuple[int, int]:
    critical = high = 0
    results = doc.get("Results") or []
    if not isinstance(results, list):
        raise EvidenceError("evidence.security.trivy.Results must be a list")
    for result in results:
        if not isinstance(result, dict):
            continue
        vulns = result.get("Vulnerabilities") or []
        if not isinstance(vulns, list):
            continue
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            severity = str(vuln.get("Severity", "")).upper()
            if severity == "CRITICAL":
                critical += 1
            elif severity == "HIGH":
                high += 1
    return critical, high


def _count_kyverno_failures(doc: dict) -> int:
    results = doc.get("results") or doc.get("Results") or []
    if not isinstance(results, list):
        raise EvidenceError("evidence.security.kyverno.results must be a list")
    failures = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        status = str(result.get("result", result.get("status", ""))).lower()
        if status in {"fail", "failed", "error"}:
            failures += 1
    return failures


def _first_number(source: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in source and source[key] is not None:
            number = _as_number(source[key])
            if number is not None:
                return number
    return None


def _has_text(source: dict, *keys: str) -> bool:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _explicit_bool(source: dict, *keys: str) -> bool | None:
    for key in keys:
        if key in source and source[key] is not None:
            return _as_bool(source[key])
    return None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value)
        return None
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUE:
            return True
        if token in _FALSE:
            return False
    return None
