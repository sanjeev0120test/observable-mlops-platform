"""
Great Expectations 1.x checks for in-memory DataFrames.

    from eval.data_quality import between, in_set, not_null, validate
    results = validate(df, {"cpu_range": between("cpu_usage_pct", 0, 100)})
    # {"cpu_range": True}

GE is imported lazily so `eval` stays importable without it.
"""

from __future__ import annotations

import uuid
from typing import Any

Check = tuple[str, dict[str, Any]]


def between(column: str, min_value: float, max_value: float) -> Check:
    return (
        "ExpectColumnValuesToBeBetween",
        {"column": column, "min_value": min_value, "max_value": max_value},
    )


def not_null(column: str) -> Check:
    return ("ExpectColumnValuesToNotBeNull", {"column": column})


def in_set(column: str, values: list[Any]) -> Check:
    return ("ExpectColumnValuesToBeInSet", {"column": column, "value_set": list(values)})


def unique(column: str) -> Check:
    return ("ExpectColumnValuesToBeUnique", {"column": column})


def validate(df: Any, checks: dict[str, Check]) -> dict[str, bool]:
    """Run each named expectation against `df`; return name -> success."""
    import great_expectations as gx

    context = gx.get_context(mode="ephemeral")
    batch = (
        context.data_sources.add_pandas(f"pandas-{uuid.uuid4().hex[:8]}")
        .add_dataframe_asset("frame")
        .add_batch_definition_whole_dataframe("whole")
        .get_batch(batch_parameters={"dataframe": df})
    )
    return {
        name: bool(batch.validate(getattr(gx.expectations, cls)(**kwargs)).success)
        for name, (cls, kwargs) in checks.items()
    }
