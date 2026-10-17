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

# ─── TRUST SCORE GATE TESTS ───────────────────────────────────────────────────

_good_metrics := {
	"accuracy": 0.92,
	"drift_score": 0.03,
	"test_dataset_size": 1000,
	"shap_values_logged": true,
}

test_allow_production_with_good_trust if {
	allow with input as {
		"model_name": "m",
		"new_version": "9",
		"metrics": _good_metrics,
		"requestor": "mlops-engineer",
		"environment": "production",
		"trust": {"score": 812, "band": "GOOD", "ledger_integrity_ok": true},
	}
}

test_deny_production_with_fair_trust if {
	not allow with input as {
		"model_name": "m",
		"new_version": "9",
		"metrics": _good_metrics,
		"requestor": "mlops-engineer",
		"environment": "production",
		"trust": {"score": 650, "band": "FAIR", "ledger_integrity_ok": true},
	}
}

test_allow_staging_with_fair_trust if {
	allow with input as {
		"model_name": "m",
		"new_version": "9",
		"metrics": _good_metrics,
		"requestor": "mlops-engineer",
		"environment": "staging",
		"trust": {"score": 650, "band": "FAIR", "ledger_integrity_ok": true},
	}
}

test_deny_staging_when_subprime if {
	reasons := deny_reasons with input as {
		"model_name": "m",
		"new_version": "9",
		"metrics": _good_metrics,
		"requestor": "mlops-engineer",
		"environment": "staging",
		"trust": {"score": 540, "band": "SUBPRIME", "ledger_integrity_ok": true},
	}
	count(reasons) == 1
	some r in reasons
	contains(r, "SUBPRIME")
}

test_deny_when_ledger_integrity_failed if {
	not allow with input as {
		"model_name": "m",
		"new_version": "9",
		"metrics": _good_metrics,
		"requestor": "mlops-engineer",
		"environment": "production",
		"trust": {"score": 950, "band": "PRIME", "ledger_integrity_ok": false},
	}
}

test_trust_is_optional_for_backward_compatibility if {
	allow with input as {
		"model_name": "m",
		"new_version": "9",
		"metrics": _good_metrics,
		"requestor": "mlops-engineer",
		"environment": "production",
	}
}
