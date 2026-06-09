"""
Feast feature definitions for the Observable MLOps Platform.
UC5: Training-serving feature skew detection uses offline vs online store comparison.

Feast 0.40.0+ API:
- Entity: name, description (no join_key, no value_type)
- FeatureView: schema=[Field(...)], not features=[Feature(...)]
- FileSource: path, timestamp_field (not event_timestamp_column)
"""

from datetime import timedelta

from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32, Int64, String

# ---------- Entities ----------
pod_entity = Entity(
    name="pod_name",
    description="Kubernetes pod identifier (namespace/pod-name)",
)

namespace_entity = Entity(
    name="namespace",
    description="Kubernetes namespace",
)

# ---------- Data sources ----------
pod_metrics_source = FileSource(
    path="data/synthetic/pod_metrics.parquet",
    timestamp_field="timestamp",
)

cost_source = FileSource(
    path="data/synthetic/cost_data.parquet",
    timestamp_field="hour",
)

# ---------- Feature views ----------
pod_health_fv = FeatureView(
    name="pod_health_features",
    entities=[pod_entity],
    ttl=timedelta(hours=1),
    schema=[
        Field(name="cpu_usage_pct", dtype=Float32),
        Field(name="mem_usage_pct", dtype=Float32),
        Field(name="restart_count", dtype=Int64),
    ],
    online=True,
    source=pod_metrics_source,
    tags={"uc": "UC1,UC4,UC5", "team": "team-ml"},
)

namespace_cost_fv = FeatureView(
    name="namespace_cost_features",
    entities=[namespace_entity],
    ttl=timedelta(hours=24),
    schema=[
        Field(name="hourly_cost_usd", dtype=Float32),
        Field(name="waste_ratio", dtype=Float32),
        Field(name="cpu_requested", dtype=Float32),
        Field(name="cpu_actual", dtype=Float32),
        Field(name="mem_requested_gi", dtype=Float32),
        Field(name="mem_actual_gi", dtype=Float32),
    ],
    online=True,
    source=cost_source,
    tags={"uc": "UC10", "team": "team-finance"},
)
