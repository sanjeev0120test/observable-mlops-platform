"""eval.data_quality runs Great Expectations 1.x checks on in-memory frames."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

pytest.importorskip("great_expectations")

from eval.data_quality import between, in_set, not_null, unique, validate  # noqa: E402

NAMESPACES = ["payments", "auth"]


def test_clean_frame_passes_every_check():
    df = pd.DataFrame(
        {"cpu": [10.0, 55.5, 99.0], "ns": ["payments", "auth", "auth"], "id": [1, 2, 3]}
    )
    results = validate(
        df,
        {
            "cpu_range": between("cpu", 0, 100),
            "ns_set": in_set("ns", NAMESPACES),
            "ns_not_null": not_null("ns"),
            "id_unique": unique("id"),
        },
    )
    assert results == {"cpu_range": True, "ns_set": True, "ns_not_null": True, "id_unique": True}


def test_bad_rows_are_caught():
    df = pd.DataFrame({"cpu": [150.0, -5.0], "ns": ["invalid", None], "id": [7, 7]})
    results = validate(
        df,
        {
            "cpu_range": between("cpu", 0, 100),
            "ns_set": in_set("ns", NAMESPACES),
            "ns_not_null": not_null("ns"),
            "id_unique": unique("id"),
        },
    )
    assert not any(results.values()), results


def test_repeated_calls_do_not_collide():
    df = pd.DataFrame({"cpu": [1.0]})
    for _ in range(3):
        assert validate(df, {"ok": between("cpu", 0, 100)}) == {"ok": True}
