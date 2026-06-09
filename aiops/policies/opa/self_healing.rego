package platform.self_healing

import future.keywords.contains
import future.keywords.if
import future.keywords.in

# OPA policy: Gate every autonomous remediation action.
# Called by the self-healing service (UC6) before executing any kubectl/API action.

default allow := false

# Helper: check if target namespace is protected (system/operator namespaces)
is_protected_ns if { input.target.namespace == "kube-system" }
is_protected_ns if { input.target.namespace == "cert-manager" }
is_protected_ns if { input.target.namespace == "kyverno" }
is_protected_ns if { input.target.namespace == "keda" }

# Base allow: no deny reasons AND not a protected namespace
allow if {
    not is_protected_ns
    count(deny_reasons) == 0
}

# Override allow: CrashLoopBackOff restart in non-protected namespace
allow if {
    input.action == "restart_pod"
    input.trigger.alert_name == "PodCrashLoopBackOff"
    not is_protected_ns
}

# Override allow: KEDA-triggered scaling in non-protected namespace
allow if {
    input.action == "scale_deployment"
    input.trigger.alert_name in {"HighCPUPreScale", "KafkaLag"}
    not is_protected_ns
}

# Override allow: dry-run mode (testing only) in non-protected namespace
allow if {
    input.dry_run == true
    not is_protected_ns
}

# Deny: destructive actions require critical severity
deny_reasons contains reason if {
    input.action in {"drain_node", "rollback_deployment"}
    input.trigger.severity != "critical"
    reason := sprintf("action '%s' requires critical severity, got '%s'", [input.action, input.trigger.severity])
}

# Deny: protected namespace — manual intervention required
deny_reasons contains reason if {
    is_protected_ns
    reason := sprintf("namespace '%s' is protected — manual intervention required", [input.target.namespace])
}
