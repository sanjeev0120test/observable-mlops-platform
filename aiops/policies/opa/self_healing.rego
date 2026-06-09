package platform.self_healing

import future.keywords.contains
import future.keywords.if
import future.keywords.in

# OPA policy: Gate every autonomous remediation action.
# Called by the self-healing service (UC6) before executing any kubectl/API action.
#
# Input shape:
#   {
#     "action": "restart_pod" | "scale_deployment" | "rollback_deployment" | "drain_node",
#     "target": { "namespace": string, "name": string },
#     "trigger": { "alert_name": string, "severity": string, "value": float },
#     "dry_run": bool
#   }

default allow := false

_protected_namespaces := {"kube-system", "cert-manager", "kyverno", "keda"}

_is_protected if {
    _protected_namespaces[input.target.namespace]
}

# Promotion is allowed when no deny reasons exist AND namespace is not protected
allow if {
    not _is_protected
    count(deny_reasons) == 0
}

# Allow restart_pod for CrashLoopBackOff in non-protected namespaces
allow if {
    input.action == "restart_pod"
    input.trigger.alert_name == "PodCrashLoopBackOff"
    not _is_protected
}

# Allow scale_deployment when KEDA signals in non-protected namespace
allow if {
    input.action == "scale_deployment"
    input.trigger.alert_name in {"HighCPUPreScale", "KafkaLag"}
    not _is_protected
}

# Always allow in dry-run mode (for non-protected namespaces only)
allow if {
    input.dry_run == true
    not _is_protected
}

# Deny: destructive actions in non-critical severity
deny_reasons contains reason if {
    input.action in {"drain_node", "rollback_deployment"}
    input.trigger.severity != "critical"
    reason := sprintf("action '%s' requires critical severity, got '%s'", [input.action, input.trigger.severity])
}

# Deny: actions on protected namespaces
deny_reasons contains reason if {
    _protected_namespaces[input.target.namespace]
    reason := sprintf("namespace '%s' is protected — manual intervention required", [input.target.namespace])
}
