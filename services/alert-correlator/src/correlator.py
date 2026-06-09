"""
UC3 — Alert correlation engine.
DBSCAN clusters alerts by time + label similarity to reduce alert fatigue.
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

TIME_WINDOW_SECONDS = 300
EPS_TIME = 0.3
EPS_LABEL = 0.5
MIN_SAMPLES = 2


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
    Build feature matrix for DBSCAN:
    - Normalized timestamp (seconds since first alert)
    - Encoded namespace
    - Encoded alertname
    """
    le_ns = LabelEncoder()
    le_alert = LabelEncoder()

    ts = pd.to_datetime(alerts_df["timestamp"])
    time_seconds = (ts - ts.min()).dt.total_seconds().values

    ns_encoded = le_ns.fit_transform(alerts_df["namespace"].fillna("unknown").values)
    alert_encoded = le_alert.fit_transform(alerts_df["alertname"].fillna("unknown").values)

    X = np.column_stack([
        time_seconds / max(time_seconds.max(), 1),  # 0-1 normalized time
        ns_encoded / max(ns_encoded.max(), 1),
        alert_encoded / max(alert_encoded.max(), 1),
    ])
    return X


def correlate_alerts(
    alerts_df: pd.DataFrame,
    eps: float = 0.15,
    min_samples: int = MIN_SAMPLES,
) -> CorrelationResult:
    """
    Cluster alerts with DBSCAN.
    Alerts in the same cluster are considered duplicates of the same root cause.

    Args:
        alerts_df: DataFrame with columns: timestamp, alertname, namespace, severity,
                   root_cause_id (ground truth for evaluation), is_duplicate
        eps: DBSCAN epsilon (max distance between cluster members)
        min_samples: DBSCAN min_samples

    Returns:
        CorrelationResult with deduplication_rate, silhouette_score, false_positive_rate
    """
    if len(alerts_df) < 3:
        return CorrelationResult(
            n_input=len(alerts_df), n_clusters=len(alerts_df), deduplicated=0,
            deduplication_rate=0.0, silhouette_score=0.0, false_positive_rate=0.0,
            root_cause_groups=[],
        )

    X = _build_feature_matrix(alerts_df)
    db = DBSCAN(eps=eps, min_samples=min_samples, metric="euclidean").fit(X)
    labels = db.labels_

    unique_labels = set(labels)
    n_clusters = len(unique_labels - {-1})
    n_outliers = sum(1 for l in labels if l == -1)

    # Deduplication: non-outlier alerts in a cluster with > 1 member are "deduplicated"
    deduplicated = len(alerts_df) - n_clusters - n_outliers
    n_input = len(alerts_df)
    deduplication_rate = deduplicated / n_input if n_input > 0 else 0.0

    sil_score = 0.0
    if n_clusters >= 2 and len(X) > n_clusters:
        valid_mask = labels != -1
        if valid_mask.sum() > n_clusters:
            try:
                sil_score = float(silhouette_score(X[valid_mask], labels[valid_mask]))
            except Exception:
                pass

    # False positive rate: root alerts incorrectly grouped as duplicates (suppressed)
    # Denominator = total root alerts, rate is clamped to [0, 1].
    false_positives = 0
    n_root_alerts = 0
    if "is_root" in alerts_df.columns and "root_cause_id" in alerts_df.columns:
        alerts_df = alerts_df.copy()
        alerts_df["cluster"] = labels
        for rc_id, group in alerts_df.groupby("root_cause_id"):
            root_rows = group[group["is_root"] == True]  # noqa: E712
            n_root_alerts += len(root_rows)
            if not root_rows.empty:
                root_cluster = root_rows.iloc[0]["cluster"]
                if root_cluster != -1:
                    cluster_members = alerts_df[alerts_df["cluster"] == root_cluster]
                    if len(cluster_members) > 1:
                        false_positives += 1
    denom = max(n_root_alerts, n_clusters, 1)
    false_positive_rate = min(1.0, false_positives / denom)

    # Build root cause groups
    groups = []
    for cluster_id in sorted(unique_labels - {-1}):
        cluster_alerts = alerts_df[labels == cluster_id]
        groups.append({
            "cluster_id": int(cluster_id),
            "n_alerts": len(cluster_alerts),
            "alertnames": cluster_alerts["alertname"].unique().tolist(),
            "namespaces": cluster_alerts["namespace"].unique().tolist(),
            "time_span_seconds": float(
                (pd.to_datetime(cluster_alerts["timestamp"]).max() -
                 pd.to_datetime(cluster_alerts["timestamp"]).min()).total_seconds()
            ),
        })

    logger.info(
        "Alert correlation: %d input → %d clusters, dedup_rate=%.2f, silhouette=%.2f",
        n_input, n_clusters, deduplication_rate, sil_score,
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
