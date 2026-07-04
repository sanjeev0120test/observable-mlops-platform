"""
UC3 — Alert correlation engine.
DBSCAN clusters alerts by time + label similarity to reduce alert fatigue.

Design notes:
- eps=0.15 tuned for typical platform alert volumes (100-2000 alerts/window)
- TIME_WEIGHT, NAMESPACE_WEIGHT, ALERT_WEIGHT control feature importance in distance
- false_positive_rate computed only when ground-truth columns present
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger(__name__)

# Feature weights in the DBSCAN distance space
# Tune: higher TIME_WEIGHT = cluster more aggressively by time proximity
TIME_WEIGHT = 0.6       # Temporal proximity is the strongest signal
NAMESPACE_WEIGHT = 0.3  # Same namespace = likely same blast radius
ALERT_WEIGHT = 0.1      # Same alert type matters but less than time+namespace

MIN_SAMPLES = 2         # Minimum cluster size — single alerts remain as outliers


@dataclass
class CorrelationResult:
    n_input: int
    n_clusters: int
    deduplicated: int
    deduplication_rate: float
    silhouette_score: float
    false_positive_rate: float
    root_cause_groups: list[dict]


def _build_feature_matrix(alerts_df: pd.DataFrame) -> np.ndarray:
    """
    Build weighted feature matrix for DBSCAN:
    - TIME_WEIGHT * normalized timestamp (seconds since first alert)
    - NAMESPACE_WEIGHT * encoded namespace
    - ALERT_WEIGHT * encoded alertname
    """
    le_ns = LabelEncoder()
    le_alert = LabelEncoder()

    ts = pd.to_datetime(alerts_df["timestamp"])
    time_seconds = (ts - ts.min()).dt.total_seconds().values

    ns_encoded = le_ns.fit_transform(alerts_df["namespace"].fillna("unknown").values)
    alert_encoded = le_alert.fit_transform(alerts_df["alertname"].fillna("unknown").values)

    # Normalize each dimension to [0, 1] then apply weights
    time_norm = time_seconds / max(float(time_seconds.max()), 1.0)
    ns_norm = ns_encoded.astype(float) / max(float(ns_encoded.max()), 1.0)
    alert_norm = alert_encoded.astype(float) / max(float(alert_encoded.max()), 1.0)

    X = np.column_stack([
        TIME_WEIGHT * time_norm,
        NAMESPACE_WEIGHT * ns_norm,
        ALERT_WEIGHT * alert_norm,
    ])
    return X


def correlate_alerts(
    alerts_df: pd.DataFrame,
    eps: float = 0.15,
    min_samples: int = MIN_SAMPLES,
) -> CorrelationResult:
    """
    Cluster alerts with DBSCAN to reduce alert fatigue.
    Alerts in the same cluster are considered duplicates of the same root cause.

    Args:
        alerts_df: DataFrame with columns: timestamp, alertname, namespace, severity.
                   Optional ground-truth columns: root_cause_id, is_root (for FPR computation).
        eps: DBSCAN epsilon (max weighted distance between cluster members). Default 0.15.
        min_samples: Minimum cluster size. Default 2.

    Returns:
        CorrelationResult with deduplication_rate, silhouette_score, false_positive_rate.
    """
    if len(alerts_df) < 3:
        return CorrelationResult(
            n_input=len(alerts_df),
            n_clusters=len(alerts_df),
            deduplicated=0,
            deduplication_rate=0.0,
            silhouette_score=0.0,
            false_positive_rate=0.0,
            root_cause_groups=[],
        )

    # Always work on a copy to avoid modifying caller's DataFrame
    df = alerts_df.copy()
    df = df.reset_index(drop=True)  # Ensure integer RangeIndex for safe numpy indexing

    X = _build_feature_matrix(df)
    db = DBSCAN(eps=eps, min_samples=min_samples, metric="euclidean").fit(X)
    labels = db.labels_

    # Attach cluster labels to DataFrame for subsequent group operations
    df["cluster"] = labels

    unique_labels = set(labels)
    n_clusters = len(unique_labels - {-1})
    n_outliers = int((labels == -1).sum())

    # Deduplication = alerts collapsed into a cluster (cluster size > 1)
    # Each cluster contributes 1 "representative" alert; rest are deduplicated
    deduplicated = max(0, len(df) - n_clusters - n_outliers)
    n_input = len(df)
    deduplication_rate = deduplicated / n_input if n_input > 0 else 0.0

    sil_score = 0.0
    if n_clusters >= 2:
        valid_mask = labels != -1
        if valid_mask.sum() > n_clusters:
            try:
                sil_score = float(silhouette_score(X[valid_mask], labels[valid_mask]))
            except Exception:
                pass

    # False positive rate: root cause alerts incorrectly suppressed
    # Only computed when ground-truth columns are present
    false_positives = 0
    n_root_alerts = 0
    if "is_root" in df.columns and "root_cause_id" in df.columns:
        for _rc_id, group in df.groupby("root_cause_id"):
            root_rows = group[group["is_root"].astype(bool)]
            n_root_alerts += len(root_rows)
            if not root_rows.empty:
                root_cluster = root_rows.iloc[0]["cluster"]
                if root_cluster != -1:
                    # Root alert was clustered — check if it was grouped with non-root alerts
                    cluster_members = df[df["cluster"] == root_cluster]
                    non_root_in_cluster = cluster_members[~cluster_members["is_root"].astype(bool)]
                    if len(non_root_in_cluster) > 0:
                        false_positives += 1

    denom = max(n_root_alerts, n_clusters, 1)
    false_positive_rate = min(1.0, false_positives / denom)

    # Build root cause groups for downstream consumption
    groups = []
    for cluster_id in sorted(unique_labels - {-1}):
        cluster_alerts = df[df["cluster"] == cluster_id]
        time_span = float(
            (
                pd.to_datetime(cluster_alerts["timestamp"]).max()
                - pd.to_datetime(cluster_alerts["timestamp"]).min()
            ).total_seconds()
        )
        groups.append({
            "cluster_id": int(cluster_id),
            "n_alerts": int(len(cluster_alerts)),
            "alertnames": cluster_alerts["alertname"].unique().tolist(),
            "namespaces": cluster_alerts["namespace"].unique().tolist(),
            "time_span_seconds": time_span,
            "severity": cluster_alerts["severity"].mode()[0]
            if "severity" in cluster_alerts.columns
            else "unknown",
        })

    logger.info(
        "Alert correlation: %d input → %d clusters (%d outliers), "
        "dedup_rate=%.2f, silhouette=%.2f, fpr=%.2f",
        n_input,
        n_clusters,
        n_outliers,
        deduplication_rate,
        sil_score,
        false_positive_rate,
    )

    return CorrelationResult(
        n_input=n_input,
        n_clusters=n_clusters,
        deduplicated=deduplicated,
        deduplication_rate=round(deduplication_rate, 4),
        silhouette_score=round(sil_score, 4),
        false_positive_rate=round(false_positive_rate, 4),
        root_cause_groups=groups,
    )
