"""
Feast feature definitions for the Observable MLOps Platform.
UC5: Training-serving feature skew detection uses offline vs online store comparison.
"""

from datetime import timedelta

import pandas as pd
from feast import Entity, Feature, FeatureView, FileSource, ValueType

# ---------- Entities ----------
pod_entity = Entity(
    name="pod_name",
    join_key="pod_name",
    value_type=ValueType.STRING,
    description="Kubernetes pod identifier (namespace/pod-name)",
)

namespace_entity = Entity(
    name="namespace",
    join_key="namespace",
    value_type=ValueType.STRING,
    description="Kubernetes namespace",
)

# ---------- Data sources ----------
pod_metrics_source = FileSource(
    path="data/synthetic/pod_metrics.parquet",
    event_timestamp_column="timestamp",
    created_timestamp_column=None,
)

cost_source = FileSource(
    path="data/synthetic/cost_data.parquet",
    event_timestamp_column="hour",
    created_timestamp_column=None,
)

# ---------- Feature views ----------
pod_health_fv = FeatureView(
    name="pod_health_features",
    entities=[pod_entity],
    ttl=timedelta(hours=1),
    features=[
        Feature(name="cpu_usage_pct", dtype=ValueType.FLOAT),
        Feature(name="mem_usage_pct", dtype=ValueType.FLOAT),
        Feature(name="restart_count", dtype=ValueType.INT64),
    ],
    online=True,
    source=pod_metrics_source,
    tags={"uc": "UC1,UC4,UC5", "team": "team-ml"},
)

namespace_cost_fv = FeatureView(
    name="namespace_cost_features",
    entities=[namespace_entity],
    ttl=timedelta(hours=24),
    features=[
        Feature(name="hourly_cost_usd", dtype=ValueType.FLOAT),
        Feature(name="waste_ratio", dtype=ValueType.FLOAT),
        Feature(name="cpu_requested", dtype=ValueType.FLOAT),
        Feature(name="cpu_actual", dtype=ValueType.FLOAT),
        Feature(name="mem_requested_gi", dtype=ValueType.FLOAT),
        Feature(name="mem_actual_gi", dtype=ValueType.FLOAT),
    ],
    online=True,
    source=cost_source,
    tags={"uc": "UC10", "team": "team-finance"},
)
