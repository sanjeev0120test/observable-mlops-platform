"""
Unit tests for the online-evaluation / shadow-mode engine.
Verifies metrics maths and the fail-safe promotion gate (never promote unless
every criterion passes).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "platform" / "shadow-mode"))

from shadow_evaluator import (  # noqa: E402
    BinaryShadowEvaluator,
    ForecastGate,
    ForecastShadowEvaluator,
    PromotionGate,
)


class TestBinaryShadowEvaluator:
    def test_confusion_and_metrics(self):
        ev = BinaryShadowEvaluator()
        # 8 TP, 1 FP, 1 FN, 90 TN
        for _ in range(8):
            ev.add(True, True)
        ev.add(True, False)  # FP
        ev.add(False, True)  # FN
        for _ in range(90):
            ev.add(False, False)
        assert ev.n == 100
        assert ev.tp == 8 and ev.fp == 1 and ev.fn == 1 and ev.tn == 90
        assert abs(ev.precision - 8 / 9) < 1e-6
        assert abs(ev.recall - 8 / 9) < 1e-6
        assert 0.0 <= ev.f1 <= 1.0

    def test_gate_blocks_on_insufficient_samples(self):
        ev = BinaryShadowEvaluator(gate=PromotionGate(min_samples=50))
        for _ in range(10):
            ev.add(True, True)
        result = ev.promotion()
        assert result["should_promote"] is False
        assert any("insufficient samples" in r for r in result["blocking_reasons"])

    def test_gate_blocks_on_high_false_positive_rate(self):
        ev = BinaryShadowEvaluator(
            gate=PromotionGate(
                min_samples=10, min_precision=0.0, min_recall=0.0, max_false_positive_rate=0.05
            )
        )
        for _ in range(10):
            ev.add(True, False)  # all false positives
        result = ev.promotion()
        assert result["should_promote"] is False
        assert any("FPR" in r for r in result["blocking_reasons"])

    def test_gate_promotes_when_all_criteria_met(self):
        ev = BinaryShadowEvaluator(
            gate=PromotionGate(
                min_samples=50, min_precision=0.9, min_recall=0.8, max_false_positive_rate=0.05
            )
        )
        for _ in range(90):
            ev.add(True, True)  # perfect TP
        for _ in range(10):
            ev.add(False, False)  # TN
        result = ev.promotion()
        assert result["should_promote"] is True
        assert result["blocking_reasons"] == []

    def test_empty_evaluator_is_safe(self):
        ev = BinaryShadowEvaluator()
        assert ev.precision == 0.0 and ev.recall == 0.0 and ev.f1 == 0.0
        assert ev.promotion()["should_promote"] is False


class TestForecastShadowEvaluator:
    def test_perfect_forecast_promotes(self):
        ev = ForecastShadowEvaluator(gate=ForecastGate(min_samples=10))
        for i in range(20):
            ev.add(predicted=float(i), actual=float(i))
        result = ev.promotion()
        assert ev.mae == 0.0
        assert result["should_promote"] is True

    def test_bad_forecast_blocked(self):
        ev = ForecastShadowEvaluator(gate=ForecastGate(min_samples=10, max_mae_pct=0.15))
        for i in range(20):
            ev.add(predicted=float(i) * 2 + 5, actual=float(i) + 1)
        result = ev.promotion()
        assert result["should_promote"] is False
        assert len(result["blocking_reasons"]) >= 1

    def test_within_tolerance_rate(self):
        ev = ForecastShadowEvaluator(gate=ForecastGate(tolerance_pct=0.10))
        ev.add(100, 100)  # exact -> within tol
        ev.add(105, 100)  # 5% -> within tol
        ev.add(200, 100)  # 100% -> outside tol
        assert abs(ev.within_tolerance_rate - 2 / 3) < 1e-6
