"""
Online evaluation / shadow-mode engine.

Problem it solves
-----------------
Model-driven decisions (self-healing "would-remediate", predictive-scaler
forecasts, drift/anomaly flags) must be proven SAFE before they act on
production. Shadow mode runs the model live, records what it WOULD have done,
compares against ground truth (human approval, realized load, confirmed
incident), and only recommends promotion to "active" once measured quality
clears a gate. This is fail-safe by construction: no promotion => stays shadow.

Two evaluators:
  - BinaryShadowEvaluator:   for allow/deny, incident/no-incident decisions.
  - ForecastShadowEvaluator: for numeric predictions (e.g. request load).

Both are pure-Python (no heavy deps) so they run in CI and any service image.
The KServe traffic-mirroring manifest lives beside this file (kserve-shadow.yaml);
this module scores what the mirrored/shadow path produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromotionGate:
    """Thresholds a shadow model must clear before it can go active."""

    min_samples: int = 50
    min_precision: float = 0.90
    min_recall: float = 0.80
    max_false_positive_rate: float = 0.05


@dataclass
class BinaryShadowEvaluator:
    """
    Scores binary shadow decisions against ground truth.

    predicted=True  means "model would take the action / flag the event".
    actual=True     means "the action was correct / the event was real".
    """

    name: str = "binary-shadow"
    gate: PromotionGate = field(default_factory=PromotionGate)
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    def add(self, predicted: bool, actual: bool) -> None:
        predicted = bool(predicted)
        actual = bool(actual)
        if predicted and actual:
            self.tp += 1
        elif predicted and not actual:
            self.fp += 1
        elif not predicted and actual:
            self.fn += 1
        else:
            self.tn += 1

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def false_positive_rate(self) -> float:
        denom = self.fp + self.tn
        return self.fp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.n if self.n else 0.0

    def metrics(self) -> dict:
        return {
            "name": self.name,
            "n": self.n,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "f1": round(self.f1, 4),
            "accuracy": round(self.accuracy, 4),
            "confusion": {"tp": self.tp, "fp": self.fp, "tn": self.tn, "fn": self.fn},
        }

    def promotion(self) -> dict:
        """Fail-safe gate: returns should_promote=False unless ALL criteria pass."""
        reasons: list[str] = []
        if self.n < self.gate.min_samples:
            reasons.append(f"insufficient samples ({self.n} < {self.gate.min_samples})")
        if self.precision < self.gate.min_precision:
            reasons.append(f"precision {self.precision:.3f} < {self.gate.min_precision}")
        if self.recall < self.gate.min_recall:
            reasons.append(f"recall {self.recall:.3f} < {self.gate.min_recall}")
        if self.false_positive_rate > self.gate.max_false_positive_rate:
            reasons.append(
                f"FPR {self.false_positive_rate:.3f} > {self.gate.max_false_positive_rate}"
            )
        return {
            "should_promote": len(reasons) == 0,
            "blocking_reasons": reasons,
            "metrics": self.metrics(),
        }


@dataclass
class ForecastGate:
    """Thresholds a numeric shadow forecaster must clear before it can go active."""

    min_samples: int = 50
    max_mae_pct: float = 0.15  # MAE as fraction of mean actual
    min_within_tolerance_rate: float = 0.80
    tolerance_pct: float = 0.10  # a point is "good" if within 10% of actual


@dataclass
class ForecastShadowEvaluator:
    """Scores numeric shadow predictions (predicted vs realized values)."""

    name: str = "forecast-shadow"
    gate: ForecastGate = field(default_factory=ForecastGate)
    _abs_errors: list[float] = field(default_factory=list)
    _actuals: list[float] = field(default_factory=list)
    _within_tol: int = 0

    def add(self, predicted: float, actual: float) -> None:
        predicted = float(predicted)
        actual = float(actual)
        err = abs(predicted - actual)
        self._abs_errors.append(err)
        self._actuals.append(actual)
        denom = abs(actual) if actual != 0 else 1e-9
        if err / denom <= self.gate.tolerance_pct:
            self._within_tol += 1

    @property
    def n(self) -> int:
        return len(self._abs_errors)

    @property
    def mae(self) -> float:
        return sum(self._abs_errors) / self.n if self.n else 0.0

    @property
    def mae_pct(self) -> float:
        mean_actual = sum(abs(a) for a in self._actuals) / self.n if self.n else 0.0
        return self.mae / mean_actual if mean_actual else 0.0

    @property
    def within_tolerance_rate(self) -> float:
        return self._within_tol / self.n if self.n else 0.0

    def metrics(self) -> dict:
        return {
            "name": self.name,
            "n": self.n,
            "mae": round(self.mae, 4),
            "mae_pct": round(self.mae_pct, 4),
            "within_tolerance_rate": round(self.within_tolerance_rate, 4),
        }

    def promotion(self) -> dict:
        reasons: list[str] = []
        if self.n < self.gate.min_samples:
            reasons.append(f"insufficient samples ({self.n} < {self.gate.min_samples})")
        if self.mae_pct > self.gate.max_mae_pct:
            reasons.append(f"MAE% {self.mae_pct:.3f} > {self.gate.max_mae_pct}")
        if self.within_tolerance_rate < self.gate.min_within_tolerance_rate:
            reasons.append(
                f"within-tolerance {self.within_tolerance_rate:.3f} "
                f"< {self.gate.min_within_tolerance_rate}"
            )
        return {
            "should_promote": len(reasons) == 0,
            "blocking_reasons": reasons,
            "metrics": self.metrics(),
        }
