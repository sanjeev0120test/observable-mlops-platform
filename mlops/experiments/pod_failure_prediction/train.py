"""
UC4 / UC9 — Pod failure prediction model.
GradientBoostingClassifier trained on synthetic pod metrics.
Used by both UC4 (predictive scaling) and UC9 (experiment tracking + serving).
"""

from __future__ import annotations

import logging
from pathlib import Path

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import train_test_split

logger = logging.getLogger(__name__)

FEATURE_COLS = ["cpu_usage_pct", "mem_usage_pct", "restart_count"]
LABEL_COL = "will_fail"
MODEL_NAME = "pod-failure-prediction"


def create_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Create binary labels: 1 = pod will fail within next 5 minutes."""
    df = df.copy()
    df[LABEL_COL] = (
        (df["cpu_usage_pct"] > 85) | (df["mem_usage_pct"] > 90) | (df["restart_count"] > 3)
    ).astype(int)
    return df


def train_and_log(
    data_path: str = "data/synthetic/pod_metrics.parquet",
    n_estimators: int = 100,
    max_depth: int = 4,
    learning_rate: float = 0.05,
    experiment_name: str = "pod-failure-prediction",
    register_model: bool = True,
) -> dict:
    """Train model, log to MLflow, optionally register."""
    df = pd.read_parquet(data_path)
    df = create_labels(df)

    X = df[FEATURE_COLS].values
    y = df[LABEL_COL].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    mlflow.set_experiment(experiment_name)

    with mlflow.start_run(run_name=f"gbc-{n_estimators}est-{max_depth}depth") as run:
        params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
        }
        clf = GradientBoostingClassifier(**params, random_state=42)
        clf.fit(X_train, y_train)

        y_pred = clf.predict(X_test)
        y_prob = clf.predict_proba(X_test)[:, 1]

        f1 = float(f1_score(y_test, y_pred, zero_division=0))
        auc = float(roc_auc_score(y_test, y_prob))
        accuracy = float(clf.score(X_test, y_test))

        mlflow.log_params(params)
        mlflow.log_metrics({
            "f1_score": f1,
            "roc_auc": auc,
            "accuracy": accuracy,
            "test_samples": len(X_test),
        })
        mlflow.set_tags({"uc": "UC4,UC9", "feature_cols": ",".join(FEATURE_COLS)})

        model_info = mlflow.sklearn.log_model(
            clf, "model",
            registered_model_name=MODEL_NAME if register_model else None,
        )

        # Compute feature importances
        importances = dict(zip(FEATURE_COLS, clf.feature_importances_.tolist()))
        mlflow.log_dict(importances, "feature_importances.json")

        run_id = run.info.run_id
        logger.info("Training complete: F1=%.4f AUC=%.4f run_id=%s", f1, auc, run_id)

    return {
        "run_id": run_id,
        "f1_score": f1,
        "roc_auc": auc,
        "accuracy": accuracy,
        "model_name": MODEL_NAME,
    }
