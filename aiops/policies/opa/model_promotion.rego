package platform.model_promotion

import rego.v1

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
#       "shap_values_logged": bool
#     },
#     "requestor": string,
#     "environment": "staging" | "production"
#   }

default allow := false

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

# ─── Model Trust Score gate (services/model-trust) ───────────────────────────
# Optional input.trust: {"score": int 300-1000, "band": "PRIME|GOOD|FAIR|SUBPRIME"}.
# When supplied, production requires band GOOD or better (score >= 700) and nothing
# may be promoted anywhere while SUBPRIME (score < 600, rollback candidate).

production_min_trust_score := 700

subprime_trust_score := 600

deny_reasons contains reason if {
	input.environment == "production"
	input.trust.score < production_min_trust_score
	reason := sprintf("trust score %d below production minimum %d (band %s)", [input.trust.score, production_min_trust_score, input.trust.band])
}

deny_reasons contains reason if {
	input.trust.score < subprime_trust_score
	reason := sprintf("trust score %d is SUBPRIME (< %d): blocked in every environment", [input.trust.score, subprime_trust_score])
}

# A stale ledger (integrity failure) invalidates the score entirely.
deny_reasons contains reason if {
	input.trust.ledger_integrity_ok == false
	reason := "trust ledger integrity check failed: score cannot be relied upon"
}
