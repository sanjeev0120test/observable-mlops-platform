"""The promotion rehearsal scores three candidates from real checker output."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent


def _load():
    path = _REPO / "scripts" / "promotion_rehearsal.py"
    spec = importlib.util.spec_from_file_location("promotion_rehearsal", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["promotion_rehearsal"] = module
    spec.loader.exec_module(module)
    return module


def test_rehearsal_scores_and_catches_tampering(tmp_path):
    rehearsal = _load()
    rows = rehearsal.rehearse(tmp_path, opa_bin=None)
    by_version = {row["report"]["model_version"]: row["report"] for row in rows}
    assert by_version["12"]["band"] == "PRIME"
    assert by_version["12"]["signals_used"]["eu_ai_act_compliant"] is True
    assert by_version["4"]["score"] <= 599
    assert by_version["4"]["band"] == "SUBPRIME"
    assert (tmp_path / "attestation.json").exists()
    assert "opa_production" not in by_version["12"]
