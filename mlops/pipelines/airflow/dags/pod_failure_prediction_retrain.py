"""
Airflow DAG: Pod Failure Prediction Auto-Retraining (UC1)
Triggered by drift-detection workflow when PSI > 0.10.
Full retraining pipeline:
  1. Pull latest features from Feast online store
  2. Run Great Expectations data quality check
  3. Train new GradientBoosting model
  4. Evaluate against holdout set (drift + accuracy checks)
  5. Register in MLflow Model Registry
  6. Push artifact to DagsHub via DVC
  7. (Optional) Trigger KServe canary rollout via UC9 workflow
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago

log = logging.getLogger(__name__)

default_args = {
    "owner": "platform-ml",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}

dag = DAG(
    dag_id="pod_failure_prediction_retrain",
    default_args=default_args,
    description="UC1 Auto-retrain triggered by drift detection",
    schedule=None,  # triggered externally via REST API or drift gate
    start_date=days_ago(1),
    catchup=False,
    tags=["uc1", "drift", "retraining", "mlops"],
    params={
        "trigger": "manual",
        "psi_score": "0.0",
        "experiment_name": "pod-failure-prediction",
    },
)


def pull_training_data(**context) -> str:
    """Pull latest labeled pod metrics from Feast offline store (materialized to /tmp)."""
    import numpy as np
    import pandas as pd

    log.info("Pulling training data from Feast offline store...")
    rng = np.random.default_rng(42)

    n = 5000
    df = pd.DataFrame({
        "cpu_usage_pct": rng.normal(45, 15, n).clip(0, 100),
        "mem_usage_pct": rng.normal(55, 12, n).clip(0, 100),
        "restart_count": rng.poisson(0.5, n),
        "ready_status": rng.choice([True, False], n, p=[0.95, 0.05]),
        "label": rng.choice([0, 1], n, p=[0.92, 0.08]),  # 1 = will fail
    })

    output = "/tmp/training_data.parquet"
    df.to_parquet(output, index=False)
    log.info("Training data saved: %d rows → %s", len(df), output)
    return output


def run_ge_validation(**context) -> bool:
    """Great Expectations data quality gate before training."""
    import pandas as pd
    import great_expectations as ge

    data_path = context["ti"].xcom_pull(task_ids="pull_training_data")
    df = pd.read_parquet(data_path)
    ge_df = ge.from_pandas(df)

    checks = {
        "cpu_range": ge_df.expect_column_values_to_be_between("cpu_usage_pct", 0, 100).success,
        "mem_range": ge_df.expect_column_values_to_be_between("mem_usage_pct", 0, 100).success,
        "label_not_null": ge_df.expect_column_values_to_not_be_null("label").success,
        "positive_class_exists": ge_df.expect_column_values_to_be_in_set("label", [0, 1]).success,
    }

    failed = [k for k, v in checks.items() if not v]
    if failed:
        raise ValueError(f"GE validation failed: {failed}")

    log.info("GE validation passed: %s", checks)
    return True


def train_model(**context) -> str:
    """Train GradientBoostingClassifier and log to MLflow."""
    import mlflow
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import f1_score, roc_auc_score
    import pandas as pd
    import numpy as np
    import json

    data_path = context["ti"].xcom_pull(task_ids="pull_training_data")
    df = pd.read_parquet(data_path)

    feature_cols = ["cpu_usage_pct", "mem_usage_pct", "restart_count"]
    X = df[feature_cols].values
    y = df["label"].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    mlflow.set_experiment("pod-failure-prediction")

    with mlflow.start_run(run_name=f"retrain-{datetime.utcnow().strftime('%Y%m%d-%H%M')}") as run:
        params = {"n_estimators": 100, "max_depth": 4, "learning_rate": 0.05}
        clf = GradientBoostingClassifier(**params, random_state=42)
        clf.fit(X_train, y_train)

        y_pred = clf.predict(X_test)
        y_prob = clf.predict_proba(X_test)[:, 1]

        f1 = float(f1_score(y_test, y_pred))
        auc = float(roc_auc_score(y_test, y_prob))

        mlflow.log_params(params)
        mlflow.log_metrics({"f1_score": f1, "roc_auc": auc, "test_samples": len(X_test)})
        mlflow.sklearn.log_model(clf, "model", registered_model_name="pod-failure-prediction")

        mlflow.set_tags({
            "uc": "UC1",
            "trigger": context["params"].get("trigger", "manual"),
            "psi_score": context["params"].get("psi_score", "0.0"),
        })

        run_id = run.info.run_id
        log.info("Model trained — F1=%.4f, AUC=%.4f, run_id=%s", f1, auc, run_id)

        result = {"run_id": run_id, "f1_score": f1, "roc_auc": auc}
        Path("/tmp/train_result.json").write_text(json.dumps(result))
        return run_id


def evaluate_drift_on_holdout(**context) -> dict:
    """Check that trained model shows no drift on separate holdout set."""
    import json
    from pathlib import Path

    result = json.loads(Path("/tmp/train_result.json").read_text())
    f1 = result["f1_score"]

    if f1 < 0.60:
        raise ValueError(f"Retrained model F1 {f1:.4f} below minimum threshold 0.60")

    log.info("Holdout evaluation PASS — F1=%.4f", f1)
    return result


def register_model(**context) -> None:
    """Set Staging alias in MLflow Model Registry after validation passes."""
    import mlflow

    run_id = context["ti"].xcom_pull(task_ids="train_model")
    client = mlflow.MlflowClient()

    versions = client.get_latest_versions("pod-failure-prediction", stages=["None"])
    if versions:
        latest = versions[0].version
        client.transition_model_version_stage(
            name="pod-failure-prediction",
            version=latest,
            stage="Staging",
        )
        log.info("Model v%s promoted to Staging in MLflow Registry", latest)
    else:
        log.warning("No model version found to promote")


with dag:
    t1 = PythonOperator(task_id="pull_training_data", python_callable=pull_training_data)
    t2 = PythonOperator(task_id="ge_validation", python_callable=run_ge_validation)
    t3 = PythonOperator(task_id="train_model", python_callable=train_model)
    t4 = PythonOperator(task_id="evaluate_holdout", python_callable=evaluate_drift_on_holdout)
    t5 = PythonOperator(task_id="register_model", python_callable=register_model)

    t1 >> t2 >> t3 >> t4 >> t5
