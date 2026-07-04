package platform.self_healing

# Classic Rego syntax (OPA v0.65.0+).
#
# Security invariant: allow is derived from count(deny_reasons) == 0
# AND at least one explicit action rule matches.
# Removing the blanket dry_run allow prevents CI bypass of policy checks.
#
# Unit tests: aiops/policies/opa/self_healing_test.rego
# Run: opa test aiops/policies/opa/ -v

default allow = false

# Protected namespaces — never allow remediation regardless of action or trigger
protected_namespaces := {
    "kube-system",
    "cert-manager",
    "kyverno",
    "keda",
    "monitoring",
    "istio-system",
    "gatekeeper-system",
}

# Allow restart_pod for CrashLoopBackOff in non-protected namespaces
# dry_run requests must ALSO satisfy action rules — no blanket dry_run bypass
allow {
    count(deny_reasons) == 0
    input.action == "restart_pod"
    input.trigger.alert_name == "PodCrashLoopBackOff"
    not input.target.namespace in protected_namespaces
}

# Allow restart_pod for OOMKilled pods
allow {
    count(deny_reasons) == 0
    input.action == "restart_pod"
    input.trigger.alert_name == "PodOOMKilled"
    not input.target.namespace in protected_namespaces
}

# Allow scale_deployment for CPU-triggered pre-scale alerts
allow {
    count(deny_reasons) == 0
    input.action == "scale_deployment"
    input.trigger.alert_name == "HighCPUPreScale"
    not input.target.namespace in protected_namespaces
}

# Allow scale_deployment for Kafka lag (KEDA consumer lag)
allow {
    count(deny_reasons) == 0
    input.action == "scale_deployment"
    input.trigger.alert_name == "KafkaLag"
    not input.target.namespace in protected_namespaces
}

# Allow rollback_deployment only for critical severity in non-protected namespaces
allow {
    count(deny_reasons) == 0
    input.action == "rollback_deployment"
    input.trigger.severity == "critical"
    not input.target.namespace in protected_namespaces
}

# Allow drain_node only for critical node-level alerts
allow {
    count(deny_reasons) == 0
    input.action == "drain_node"
    input.trigger.severity == "critical"
    input.trigger.alert_name == "NodeNotReady"
    not input.target.namespace in protected_namespaces
}

# deny_reasons partial set (all deny conditions — allow is derived from count == 0)
deny_reasons[reason] {
    input.target.namespace in protected_namespaces
    reason := sprintf("namespace '%v' is protected — remediation never allowed", [input.target.namespace])
}

deny_reasons[reason] {
    input.action == "drain_node"
    input.trigger.severity != "critical"
    reason := "action 'drain_node' requires trigger severity=critical"
}

deny_reasons[reason] {
    input.action == "rollback_deployment"
    input.trigger.severity != "critical"
    reason := "action 'rollback_deployment' requires trigger severity=critical"
}

deny_reasons[reason] {
    not input.action in {"restart_pod", "scale_deployment", "rollback_deployment", "drain_node"}
    reason := sprintf("action '%v' is not in the allowed actions list", [input.action])
}

# ── Input validation: a remediation must name a concrete target ──────────────
# Prevents malformed/ambiguous requests from ever being allowed.
deny_reasons[reason] {
    input.action == "restart_pod"
    not input.target.pod
    reason := "action 'restart_pod' requires target.pod"
}

deny_reasons[reason] {
    input.action == "scale_deployment"
    not input.target.deployment
    reason := "action 'scale_deployment' requires target.deployment"
}

deny_reasons[reason] {
    input.action == "rollback_deployment"
    not input.target.deployment
    reason := "action 'rollback_deployment' requires target.deployment"
}

deny_reasons[reason] {
    input.action == "drain_node"
    not input.target.node
    reason := "action 'drain_node' requires target.node"
}

# ── Blast-radius cap: scaling may not exceed a hard replica ceiling ──────────
max_scale_replicas := 50

deny_reasons[reason] {
    input.action == "scale_deployment"
    input.target.replicas > max_scale_replicas
    reason := sprintf(
        "scale_deployment replicas %v exceeds blast-radius cap %v",
        [input.target.replicas, max_scale_replicas],
    )
}
