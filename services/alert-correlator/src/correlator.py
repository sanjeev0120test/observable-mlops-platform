"""
UC3 — Alert correlation engine.
DBSCAN clusters alerts by time + label similarity to reduce alert fatigue.

Design notes:
- eps=0.15 tuned for typical platform alert volumes (100-2000 alerts/window)
- time is scaled by a fixed correlation horizon (TIME_SCALE_SECONDS) and namespace
  is one-hot encoded (NAMESPACE_WEIGHT) so the distance space is interpretable
- false_positive_rate measures cross-incident contamination, computed only when
  ground-truth columns (is_root, root_cause_id) are present
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.metrics import silhouette_score

logger = logging.getLogger(__name__)

# Temporal correlation horizon. Time is expressed in units of this window so that
# `eps` is interpretable: two alerts one full window apart sit at distance 1.0 on
# the time axis. An incident's cascade alerts fire within seconds-to-minutes of the
# root, while distinct incidents are typically tens of minutes apart, so a ~20 min
# horizon keeps intra-incident alerts inside a small eps while separating incidents.
TIME_SCALE_SECONDS = 1200.0

# Secondary blast-radius signal. Namespace is one-hot encoded (not label-encoded):
# label encoding invents a meaningless ordinal distance between namespaces, which is
# what previously collapsed every alert into a single chained cluster. With one-hot,
# two different namespaces are sqrt(2) * NAMESPACE_WEIGHT apart — enough to split
# concurrent incidents in different namespaces without drowning the temporal signal.
NAMESPACE_WEIGHT = 0.20

MIN_SAMPLES = 2  # Minimum cluster size — single alerts remain as outliers


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
    Build the DBSCAN feature matrix.

    - time: seconds since the first alert, expressed in TIME_SCALE_SECONDS units.
      Using an absolute horizon (rather than min-max scaling over the whole window)
      is what makes clustering correct: min-max scaling squeezes a 24h window into
      [0, 1], so incidents 20 minutes apart end up ~0.008 apart and DBSCAN chains
      the entire timeline into one cluster.
    - namespace: one-hot encoded and scaled by NAMESPACE_WEIGHT so different
      namespaces are a fixed, meaningful distance apart.

    Alert name is intentionally excluded: cascade alerts carry different names from
    their root by design, so it is noise for grouping alerts of the same incident.
    """
    ts = pd.to_datetime(alerts_df["timestamp"], utc=True, errors="coerce")
    time_seconds = (ts - ts.min()).dt.total_seconds().fillna(0.0).to_numpy(dtype=float)
    time_feat = (time_seconds / TIME_SCALE_SECONDS).reshape(-1, 1)

    ns = alerts_df["namespace"].fillna("unknown").astype(str)
    ns_onehot = pd.get_dummies(ns).to_numpy(dtype=float) * NAMESPACE_WEIGHT

    return np.column_stack([time_feat, ns_onehot])


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

    # False positive rate: root-cause alerts incorrectly suppressed into the WRONG
    # incident. A root alert grouped with its own cascade alerts is correct and must
    # not count; the failure mode we measure is cross-incident contamination — a root
    # alert landing in a cluster that mixes more than one root_cause_id, which would
    # bury a real incident under an unrelated one.
    # Only computed when ground-truth columns are present.
    false_positives = 0
    n_root_alerts = 0
    if "is_root" in df.columns and "root_cause_id" in df.columns:
        root_rows = df[df["is_root"].astype(bool)]
        n_root_alerts = len(root_rows)
        for _, root in root_rows.iterrows():
            root_cluster = root["cluster"]
            if root_cluster == -1:
                # Left as its own outlier — not suppressed into another incident.
                continue
            cluster_members = df[df["cluster"] == root_cluster]
            if cluster_members["root_cause_id"].nunique() > 1:
                false_positives += 1

    denom = max(n_root_alerts, 1)
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
        groups.append(
            {
                "cluster_id": int(cluster_id),
                "n_alerts": int(len(cluster_alerts)),
                "alertnames": cluster_alerts["alertname"].unique().tolist(),
                "namespaces": cluster_alerts["namespace"].unique().tolist(),
                "time_span_seconds": time_span,
                "severity": (
                    cluster_alerts["severity"].mode()[0]
                    if "severity" in cluster_alerts.columns
                    else "unknown"
                ),
            }
        )

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
