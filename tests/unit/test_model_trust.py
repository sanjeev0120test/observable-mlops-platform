"""
Unit tests for the Model Trust Score engine, ledger and service.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "services" / "model-trust" / "src"))

from trust_engine import (  # noqa: E402
    BANDS,
    GENESIS_HASH,
    PILLAR_WEIGHTS,
    SCORE_CEILING,
    SCORE_FLOOR,
    UNOBSERVED_HEALTH,
    TrustLedger,
    band_for,
    compute_trust_score,
)

PERFECT = {
    "psi_score": 0.02,
    "ks_statistic": 0.03,
    "accuracy": 0.91,
    "estimated_performance_drop": 0.0,
    "error_budget_remaining": 0.8,
    "p99_latency_ms": 120,
    "cost_per_1k_predictions_usd": 0.01,
    "critical_cves": 0,
    "high_cves": 0,
    "policy_violations": 0,
    "image_signed": True,
    "shap_logged": True,
    "model_card_present": True,
    "lineage_recorded": True,
    "eu_ai_act_compliant": True,
    "human_oversight_defined": True,
}

TERRIBLE = {
    "psi_score": 0.9,
    "ks_statistic": 0.8,
    "accuracy": 0.40,
    "estimated_performance_drop": 0.5,
    "error_budget_remaining": 0.0,
    "p99_latency_ms": 5000,
    "cost_per_1k_predictions_usd": 1.0,
    "critical_cves": 5,
    "high_cves": 20,
    "policy_violations": 6,
    "image_signed": False,
    "shap_logged": False,
    "model_card_present": False,
    "lineage_recorded": False,
    "eu_ai_act_compliant": False,
    "human_oversight_defined": False,
}


class TestScoring:
    def test_weights_sum_to_one(self):
        assert abs(sum(PILLAR_WEIGHTS.values()) - 1.0) < 1e-9

    def test_perfect_inputs_hit_ceiling_and_prime(self):
        r = compute_trust_score("m", "1", PERFECT)
        assert r.score == SCORE_CEILING
        assert r.band == "PRIME"
        assert r.recommendations == []
        assert r.plan_reaches_target and r.plan_to_target == []

    def test_terrible_inputs_hit_floor_and_subprime(self):
        r = compute_trust_score("m", "1", TERRIBLE)
        assert r.score == SCORE_FLOOR
        assert r.band == "SUBPRIME"
        assert all(p.health == 0.0 for p in r.pillars)

    def test_deterministic(self):
        a = compute_trust_score("m", "1", PERFECT, now=None)
        b = compute_trust_score("m", "1", PERFECT, now=None)
        assert a.score == b.score and a.inputs_hash == b.inputs_hash

    def test_unobserved_pillars_are_penalised_not_rewarded(self):
        r = compute_trust_score("m", "1", {})
        assert all(not p.observed for p in r.pillars)
        assert all(p.health == UNOBSERVED_HEALTH for p in r.pillars)
        expected = round(SCORE_FLOOR + (SCORE_CEILING - SCORE_FLOOR) * UNOBSERVED_HEALTH)
        assert r.score == expected
        assert r.band == "SUBPRIME"

    def test_points_are_fully_attributable(self):
        r = compute_trust_score("m", "1", {**PERFECT, "psi_score": 0.3, "high_cves": 4})
        earned = sum(p.points_earned for p in r.pillars)
        assert r.caps_applied == []
        assert abs((SCORE_FLOOR + earned) - r.score) < 1.0
        assert r.score == r.score_uncapped
        drift = next(p for p in r.pillars if p.pillar == "drift")
        assert 0 < drift.health < 1 and drift.points_lost > 0

    def test_monotone_in_each_signal(self):
        base = compute_trust_score("m", "1", PERFECT).score
        for key, worse in [
            ("psi_score", 0.3),
            ("accuracy", 0.7),
            ("p99_latency_ms", 900),
            ("cost_per_1k_predictions_usd", 0.1),
            ("critical_cves", 2),
            ("shap_logged", False),
        ]:
            assert compute_trust_score("m", "1", {**PERFECT, key: worse}).score < base, key

    def test_targets_override_baseline(self):
        strict = compute_trust_score("m", "1", PERFECT, targets={"performance_baseline": 0.99})
        assert strict.score < SCORE_CEILING

    def test_bands_are_contiguous(self):
        thresholds = [t for t, _, _ in BANDS]
        assert thresholds == sorted(thresholds, reverse=True)
        assert band_for(SCORE_CEILING)[0] == "PRIME"
        assert band_for(SCORE_FLOOR)[0] == "SUBPRIME"
        assert band_for(699)[0] == "FAIR" and band_for(700)[0] == "GOOD"

    def test_rejects_bad_input(self):
        with pytest.raises(ValueError):
            compute_trust_score("", "1", PERFECT)
        with pytest.raises(ValueError):
            compute_trust_score("m", "1", PERFECT, target_band="PLATINUM")


class TestKnockoutCaps:
    def test_critical_cves_cap_overrides_great_accuracy(self):
        r = compute_trust_score("m", "1", {**PERFECT, "critical_cves": 3})
        assert r.score_uncapped > 850  # averaging alone would call this PRIME
        assert r.score <= 599 and r.band == "SUBPRIME"
        assert any(c["rule"] == "critical_cves>=3" and c["binding"] for c in r.caps_applied)
        assert r.recommendations[0].pillar == "security"
        assert r.recommendations[0].action.startswith("[LIFTS CAP]")

    def test_single_critical_cve_blocks_production_band(self):
        r = compute_trust_score("m", "1", {**PERFECT, "critical_cves": 1})
        assert r.score <= 699 and r.band == "FAIR"

    def test_unsigned_image_can_never_be_prime(self):
        r = compute_trust_score("m", "1", {**PERFECT, "image_signed": False})
        assert r.score <= 849 and r.band == "GOOD"

    def test_eu_ai_act_non_compliance_blocks_auto_promotion(self):
        r = compute_trust_score("m", "1", {**PERFECT, "eu_ai_act_compliant": False})
        assert r.band == "GOOD"

    def test_cap_lift_outranks_cheap_actions_when_pillars_unobserved(self):
        # Sparse signals: most pillars unobserved, so cheap actions (e.g. 0.5h KEDA scale)
        # have huge raw ROI. The cap lift must still come first; the rest are flagged blocked.
        r = compute_trust_score(
            "m",
            "1",
            {"accuracy": 0.93, "critical_cves": 3, "image_signed": False, "policy_violations": 2},
        )
        assert r.band == "SUBPRIME"
        assert r.recommendations[0].lifts_cap
        assert r.recommendations[0].action.startswith("[LIFTS CAP]")
        assert all(p.blocked_by_cap for p in r.recommendations if not p.lifts_cap)
        assert any(p.blocked_by_cap for p in r.recommendations)

    def test_nothing_blocked_without_caps(self):
        r = compute_trust_score("m", "1", {**PERFECT, "psi_score": 0.4})
        assert r.recommendations and not any(p.blocked_by_cap for p in r.recommendations)

    def test_no_caps_when_signals_absent(self):
        r = compute_trust_score("m", "1", {"accuracy": 0.9})
        assert r.caps_applied == []

    def test_lifting_cap_in_plan_reaches_target(self):
        r = compute_trust_score("m", "1", {**PERFECT, "critical_cves": 3}, target_band="PRIME")
        assert r.plan_reaches_target
        assert len(r.plan_to_target) == 1 and r.plan_to_target[0].pillar == "security"


class TestAdvisor:
    def test_recommendations_ranked_by_roi(self):
        r = compute_trust_score("m", "1", {**PERFECT, "psi_score": 0.6, "critical_cves": 3})
        pillars = {p.pillar for p in r.recommendations}
        assert {"drift", "security"} <= pillars
        rois = [p.points_per_hour for p in r.recommendations]
        assert rois == sorted(rois, reverse=True)

    def test_plan_reaches_target_band_with_minimal_actions(self):
        signals = {
            **PERFECT,
            "psi_score": 0.6,
            "ks_statistic": 0.5,
            "accuracy": 0.55,
            "estimated_performance_drop": 0.25,
            "critical_cves": 3,
            "policy_violations": 4,
        }
        r = compute_trust_score("m", "1", signals, target_band="GOOD")
        assert r.score < 700 and r.band in {"FAIR", "SUBPRIME"}
        assert r.plan_reaches_target
        gained = sum(p.points_recoverable for p in r.plan_to_target)
        assert r.score + gained >= 700
        # one action per pillar — recoveries inside a pillar overlap
        assert len({p.pillar for p in r.plan_to_target}) == len(r.plan_to_target)

    def test_plan_reports_when_target_unreachable(self):
        r = compute_trust_score("m", "1", TERRIBLE, target_band="PRIME")
        assert not r.plan_reaches_target
        assert r.plan_to_target_hours > 0


class TestLedger:
    def test_chain_links_and_verifies(self, tmp_path):
        led = TrustLedger(tmp_path / "ledger.jsonl")
        e1 = led.append(compute_trust_score("m", "1", PERFECT))
        e2 = led.append(compute_trust_score("m", "2", {**PERFECT, "psi_score": 0.3}))
        assert e1["prev_hash"] == GENESIS_HASH
        assert e2["prev_hash"] == e1["hash"]
        v = led.verify()
        assert v.ok and v.entries == 2 and v.head_hash == e2["hash"]
        assert led.previous_score("m") == e2["score"]
        assert led.previous_score("m", before_seq=2) == e1["score"]

    def test_tampering_is_detected_at_exact_sequence(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        led = TrustLedger(path)
        for v in range(1, 5):
            led.append(compute_trust_score("m", str(v), PERFECT))
        lines = path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(lines[2])
        tampered["score"] = 999  # rewrite history for seq 3
        lines[2] = json.dumps(tampered, sort_keys=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        v = led.verify()
        assert not v.ok and v.first_bad_seq == 3 and v.reason == "entry hash mismatch"

    def test_deletion_breaks_chain(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        led = TrustLedger(path)
        for v in range(1, 4):
            led.append(compute_trust_score("m", str(v), PERFECT))
        lines = path.read_text(encoding="utf-8").splitlines()
        del lines[1]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        v = led.verify()
        assert not v.ok and v.first_bad_seq == 2

    def test_attestation_document(self, tmp_path):
        led = TrustLedger(tmp_path / "ledger.jsonl")
        led.append(compute_trust_score("a", "1", PERFECT))
        led.append(compute_trust_score("b", "7", TERRIBLE))
        att = led.attestation()
        assert att["integrity_ok"] and att["entries"] == 2
        assert att["models_covered"] == ["a", "b"]
        assert att["latest_by_model"]["b"]["band"] == "SUBPRIME"
        assert len(att["head_hash"]) == 64

    def test_empty_ledger_verifies(self, tmp_path):
        led = TrustLedger(tmp_path / "none.jsonl")
        v = led.verify()
        assert v.ok and v.entries == 0 and v.head_hash == GENESIS_HASH


@pytest.fixture(scope="module")
def trust_app(tmp_path_factory):
    # Import once per module: prometheus_client refuses duplicate metric registration.
    import os

    os.environ["TRUST_LEDGER_PATH"] = str(tmp_path_factory.mktemp("trust") / "boot.jsonl")
    os.environ["MLFLOW_TRACKING_URI"] = ""
    # Several services expose a `main` module; load this one by path under a unique name.
    import importlib.util

    path = _REPO_ROOT / "services" / "model-trust" / "src" / "main.py"
    spec = importlib.util.spec_from_file_location("model_trust_main", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["model_trust_main"] = module
    spec.loader.exec_module(module)
    return module


class TestService:
    @pytest.fixture
    def client(self, tmp_path, trust_app):
        from fastapi.testclient import TestClient

        trust_app.ledger = TrustLedger(tmp_path / "svc.jsonl")  # fresh ledger per test
        return TestClient(trust_app.app)

    def test_health_and_bands(self, client):
        assert client.get("/health").json()["status"] == "ok"
        b = client.get("/api/v1/bands").json()
        assert [x["band"] for x in b["bands"]] == ["PRIME", "GOOD", "FAIR", "SUBPRIME"]

    def test_score_records_and_reports_delta(self, client):
        body = {"model_name": "pod-failure-prediction", "model_version": "3", "signals": PERFECT}
        r1 = client.post("/api/v1/score", json=body).json()
        assert r1["score"] == SCORE_CEILING and r1["previous_score"] is None
        assert r1["ledger_entry"]["seq"] == 1
        body["model_version"] = "4"
        body["signals"] = {**PERFECT, "psi_score": 0.45}
        r2 = client.post("/api/v1/score", json=body).json()
        assert r2["score"] < r1["score"]
        assert r2["score_delta"] == r2["score"] - r1["score"]
        assert r2["recommendations"][0]["pillar"] == "drift"

        hist = client.get("/api/v1/models/pod-failure-prediction/history").json()
        assert len(hist["entries"]) == 2 and hist["latest"]["model_version"] == "4"
        assert client.get("/api/v1/ledger/verify").json()["ok"] is True
        assert client.get("/api/v1/ledger/attestation").json()["integrity_ok"] is True

    def test_dry_scoring_does_not_touch_ledger(self, client):
        body = {"model_name": "x", "model_version": "1", "signals": PERFECT, "record": False}
        r = client.post("/api/v1/score", json=body).json()
        assert r["ledger_entry"] is None
        assert client.get("/api/v1/models/x/history").status_code == 404

    def test_metrics_exposed(self, client):
        client.post(
            "/api/v1/score", json={"model_name": "x", "model_version": "1", "signals": PERFECT}
        )
        text = client.get("/metrics").text
        assert 'model_trust_score{band="PRIME",model="x",version="1"} 1000.0' in text
        assert "model_trust_ledger_integrity_ok 1.0" in text

    def test_validation(self, client):
        assert client.post("/api/v1/score", json={"model_name": "x"}).status_code == 422
        bad = {"model_name": "x", "model_version": "1", "target_band": "GOLD"}
        assert client.post("/api/v1/score", json=bad).status_code == 422
