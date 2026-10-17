package platform.model_promotion

import rego.v1

# OPA unit tests for model_promotion.rego
# Co-located in the policy package so `allow` / `deny_reasons` resolve directly.
# Run with: opa test aiops/policies/opa/ -v

# ─── ALLOW TESTS ──────────────────────────────────────────────────────────────

test_allow_valid_staging_promotion if {
	allow with input as {
		"model_name": "pod-failure-prediction",
		"new_version": "3",
		"metrics": {
			"accuracy": 0.85,
			"drift_score": 0.05,
			"test_dataset_size": 500,
			"shap_values_logged": true,
		},
		"requestor": "mlops-engineer",
		"environment": "staging",
	}
}

test_allow_valid_production_promotion if {
	allow with input as {
		"model_name": "pod-failure-prediction",
		"new_version": "5",
		"metrics": {
			"accuracy": 0.92,
			"drift_score": 0.03,
			"test_dataset_size": 1000,
			"shap_values_logged": true,
		},
		"requestor": "mlops-engineer",
		"environment": "production",
	}
}

test_allow_minimum_thresholds_exactly if {
	allow with input as {
		"model_name": "pod-failure-prediction",
		"new_version": "6",
		"metrics": {
			"accuracy": 0.70,
			"drift_score": 0.10,
			"test_dataset_size": 100,
			"shap_values_logged": true,
		},
		"requestor": "ci-pipeline",
		"environment": "staging",
	}
}

# ─── DENY TESTS ───────────────────────────────────────────────────────────────

test_deny_low_accuracy if {
	not allow with input as {
		"model_name": "pod-failure-prediction",
		"new_version": "2",
		"metrics": {
			"accuracy": 0.65,
			"drift_score": 0.05,
			"test_dataset_size": 500,
			"shap_values_logged": true,
		},
		"requestor": "mlops-engineer",
		"environment": "production",
	}
}

test_deny_high_drift if {
	not allow with input as {
		"model_name": "pod-failure-prediction",
		"new_version": "2",
		"metrics": {
			"accuracy": 0.90,
			"drift_score": 0.25,
			"test_dataset_size": 500,
			"shap_values_logged": true,
		},
		"requestor": "mlops-engineer",
		"environment": "production",
	}
}

test_deny_insufficient_test_data if {
	not allow with input as {
		"model_name": "pod-failure-prediction",
		"new_version": "2",
		"metrics": {
			"accuracy": 0.90,
			"drift_score": 0.05,
			"test_dataset_size": 50,
			"shap_values_logged": true,
		},
		"requestor": "mlops-engineer",
		"environment": "production",
	}
}

test_deny_production_without_shap if {
	not allow with input as {
		"model_name": "pod-failure-prediction",
		"new_version": "2",
		"metrics": {
			"accuracy": 0.90,
			"drift_score": 0.05,
			"test_dataset_size": 500,
			"shap_values_logged": false,
		},
		"requestor": "mlops-engineer",
		"environment": "production",
	}
}

test_deny_anonymous_production_requestor if {
	not allow with input as {
		"model_name": "pod-failure-prediction",
		"new_version": "2",
		"metrics": {
			"accuracy": 0.90,
			"drift_score": 0.05,
			"test_dataset_size": 500,
			"shap_values_logged": true,
		},
		"requestor": "anonymous",
		"environment": "production",
	}
}

# ─── DENY_REASONS CONTENT TESTS ───────────────────────────────────────────────

test_deny_reasons_accuracy_message_correct if {
	reasons := deny_reasons with input as {
		"model_name": "pod-failure-prediction",
		"new_version": "2",
		"metrics": {
			"accuracy": 0.60,
			"drift_score": 0.05,
			"test_dataset_size": 500,
			"shap_values_logged": true,
		},
		"requestor": "ci",
		"environment": "staging",
	}
	count(reasons) == 1
}

test_multiple_deny_reasons_accumulate if {
	reasons := deny_reasons with input as {
		"model_name": "pod-failure-prediction",
		"new_version": "1",
		"metrics": {
			"accuracy": 0.50,
			"drift_score": 0.30,
			"test_dataset_size": 10,
			"shap_values_logged": false,
		},
		"requestor": "anonymous",
		"environment": "production",
	}
	count(reasons) >= 4
}
