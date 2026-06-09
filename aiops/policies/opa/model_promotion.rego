package platform.model_promotion

import future.keywords.contains
import future.keywords.if
import future.keywords.in

# OPA policy: Only allow model promotion to production if all quality gates pass.
# Called by UC9 (experiment tracking + serving) before KServe InferenceService is updated.
#
# Input shape:
#   {
#     "model_name": string,
#     "new_version": string,
#     "metrics": {
#       "accuracy": float,
#       "drift_score": float,
#       "test_dataset_size": int,
#       "training_data_hash": string
#     },
#     "requestor": string,
#     "environment": "staging" | "production"
#   }

default allow := false
default deny_reasons := []

# Promotion is allowed only when no deny reasons exist
allow if {
    count(deny_reasons) == 0
}

deny_reasons contains reason if {
    input.metrics.accuracy < 0.70
    reason := sprintf("accuracy %.3f below minimum 0.70", [input.metrics.accuracy])
}

deny_reasons contains reason if {
    input.metrics.drift_score > 0.10
    reason := sprintf("drift_score %.3f exceeds maximum 0.10", [input.metrics.drift_score])
}

deny_reasons contains reason if {
    input.metrics.test_dataset_size < 100
    reason := sprintf("test_dataset_size %d below minimum 100", [input.metrics.test_dataset_size])
}

deny_reasons contains reason if {
    input.environment == "production"
    input.requestor == "anonymous"
    reason := "production promotion requires authenticated requestor"
}

# Explainability check: model must have SHAP values logged
deny_reasons contains reason if {
    input.environment == "production"
    not input.metrics.shap_values_logged
    reason := "production models must have SHAP explainability logged (UC17)"
}
