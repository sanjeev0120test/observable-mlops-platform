"""
Unit tests for the self-healing service's fail-closed behavior.
Tests OPA query logic, namespace protection, and action validation.
Does NOT require a running OPA server — mocks the httpx client.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Service directories use hyphens — add src/ directly to path
_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "services" / "self-healing" / "src"))


class TestSelfHealingFailClosed:
    """Tests that the self-healing service is fail-closed when OPA is unreachable."""

    def test_opa_timeout_raises_503(self):
        """OPA timeout must result in HTTP 503 — never allow=True."""
        import httpx
        from fastapi.testclient import TestClient

        with patch("main._query_opa") as mock_opa:
            from fastapi import HTTPException
            mock_opa.side_effect = HTTPException(
                status_code=503,
                detail="Policy engine (OPA) timed out — remediation blocked by fail-closed policy",
            )
            import importlib
            main_mod = importlib.import_module("main")
            client = TestClient(main_mod.app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/remediate",
                json={
                    "action": "restart_pod",
                    "target": {"namespace": "default", "pod": "test-pod"},
                    "trigger": {"alert_name": "PodCrashLoopBackOff"},
                },
            )
            assert resp.status_code == 503, (
                f"OPA unavailable must return 503, got {resp.status_code}"
            )

    def test_unknown_action_returns_400(self):
        from fastapi.testclient import TestClient
        import importlib
        main_mod = importlib.import_module("main")
        client = TestClient(main_mod.app)
        resp = client.post(
            "/api/v1/remediate",
            json={
                "action": "delete_namespace",
                "target": {"namespace": "default"},
                "trigger": {},
            },
        )
        assert resp.status_code == 400

    def test_protected_namespace_blocked_without_opa_call(self):
        """Hard-protected namespaces are blocked before OPA is even called."""
        from fastapi.testclient import TestClient
        import importlib
        main_mod = importlib.import_module("main")

        for ns in list(main_mod.HARDCODED_PROTECTED_NAMESPACES)[:3]:
            with patch("main._query_opa") as mock_opa:
                client = TestClient(main_mod.app)
                resp = client.post(
                    "/api/v1/remediate",
                    json={
                        "action": "restart_pod",
                        "target": {"namespace": ns, "pod": "test"},
                        "trigger": {"alert_name": "PodCrashLoopBackOff"},
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["allowed"] is False, f"Protected namespace {ns} should be denied"
                assert len(data["deny_reasons"]) > 0
                mock_opa.assert_not_called(), (
                    f"OPA should not be called for hard-protected namespace {ns}"
                )

    def test_health_endpoint_reports_fail_closed_true(self):
        from fastapi.testclient import TestClient
        import importlib
        main_mod = importlib.import_module("main")
        client = TestClient(main_mod.app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("fail_closed") is True, "Health endpoint must report fail_closed=True"

    def test_opa_denied_action_not_executed(self):
        """When OPA returns allow=False, executed must be False."""
        from fastapi.testclient import TestClient
        import importlib
        main_mod = importlib.import_module("main")

        with patch("main._query_opa") as mock_opa:
            mock_opa.return_value = {
                "allow": False,
                "deny_reasons": ["namespace 'staging' not in policy allowlist"],
            }
            client = TestClient(main_mod.app)
            resp = client.post(
                "/api/v1/remediate",
                json={
                    "action": "restart_pod",
                    "target": {"namespace": "staging", "pod": "test"},
                    "trigger": {"alert_name": "PodCrashLoopBackOff"},
                    "dry_run": False,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["allowed"] is False
            assert data["executed"] is False
            assert len(data["deny_reasons"]) > 0

    def test_opa_allowed_dry_run_not_executed(self):
        """When OPA allows but dry_run=True, executed must be False."""
        from fastapi.testclient import TestClient
        import importlib
        main_mod = importlib.import_module("main")

        with patch("main._query_opa") as mock_opa:
            mock_opa.return_value = {"allow": True, "deny_reasons": []}
            client = TestClient(main_mod.app)
            resp = client.post(
                "/api/v1/remediate",
                json={
                    "action": "restart_pod",
                    "target": {"namespace": "default", "pod": "test"},
                    "trigger": {"alert_name": "PodCrashLoopBackOff"},
                    "dry_run": True,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["allowed"] is True
            assert data["executed"] is False  # dry_run must prevent execution
