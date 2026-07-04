"""
Unit tests for the predictive-scaler forecasting + shadow-mode behaviour.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_SRC = _REPO_ROOT / "services" / "predictive-scaler" / "src"
_MODULE_NAME = "predictive_scaler_main"


def _main():
    """Load the predictive-scaler main under a unique name (avoids 'main' collisions)."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _SRC / "main.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


class TestLinearTrendForecast:
    def test_upward_trend_projected(self):
        m = _main()
        hist = [100, 110, 120, 130, 140]
        f = m._linear_trend_forecast(hist, steps_ahead=1)
        assert f > 140  # continues the upward trend

    def test_never_negative(self):
        m = _main()
        f = m._linear_trend_forecast([10, 5, 1, 0], steps_ahead=50)
        assert f >= 0.0

    def test_short_history_seasonal_naive(self):
        m = _main()
        assert m._linear_trend_forecast([42.0], steps_ahead=5) == 42.0
        assert m._linear_trend_forecast([], steps_ahead=5) == 0.0


class TestReplicaRecommendation:
    def test_respects_min_max_bounds(self):
        m = _main()
        assert m._recommend_replicas(0) >= m.MIN_REPLICAS
        assert m._recommend_replicas(1_000_000) <= m.MAX_REPLICAS

    def test_scales_with_load(self):
        m = _main()
        low = m._recommend_replicas(100)
        high = m._recommend_replicas(1500)
        assert high >= low


class TestForecastEndpoint:
    def test_shadow_mode_does_not_apply(self):
        from fastapi.testclient import TestClient

        m = _main()
        client = TestClient(m.app)
        resp = client.post(
            "/api/v1/forecast",
            json={
                "service": "auth-service",
                "horizon_minutes": 10,
                "history_rps": [100, 120, 140, 160, 180, 200],
                "shadow": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["shadow_mode"] is True
        assert data["applied"] is False
        assert data["scale_recommendation"]["applied"] is False
        assert data["forecast_rps"] > 0

    def test_active_mode_applies(self):
        from fastapi.testclient import TestClient

        m = _main()
        client = TestClient(m.app)
        resp = client.post(
            "/api/v1/forecast",
            json={
                "service": "auth-service",
                "horizon_minutes": 5,
                "history_rps": [100, 120, 140, 160, 180],
                "shadow": False,
            },
        )
        data = resp.json()
        assert data["applied"] is True
        assert data["pre_scale_lead_time_seconds"] == 300.0

    def test_backtest_mae_reported(self):
        from fastapi.testclient import TestClient

        m = _main()
        client = TestClient(m.app)
        resp = client.post(
            "/api/v1/forecast",
            json={
                "service": "auth-service",
                "history_rps": [100, 110, 120, 130, 140, 150, 160],
            },
        )
        assert resp.json()["forecast_mae"] >= 0.0
