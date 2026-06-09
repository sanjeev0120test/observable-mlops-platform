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

allow if {
    count(deny_reasons) == 0
}

# Block destructive actions in production without critical severity
deny_reasons contains reason if {
    input.action in {"drain_node", "rollback_deployment"}
    input.trigger.severity != "critical"
    reason := sprintf("action '%s' requires critical severity, got '%s'", [input.action, input.trigger.severity])
}

# Block actions on protected namespaces
deny_reasons contains reason if {
    input.target.namespace in {"kube-system", "cert-manager", "kyverno", "keda"}
    reason := sprintf("namespace '%s' is protected — manual intervention required", [input.target.namespace])
}

# Allow restart_pod for any CrashLoopBackOff regardless of severity
allow if {
    input.action == "restart_pod"
    input.trigger.alert_name == "PodCrashLoopBackOff"
    not input.target.namespace in {"kube-system", "cert-manager", "kyverno", "keda"}
}

# Allow scale_deployment when KEDA signals
allow if {
    input.action == "scale_deployment"
    input.trigger.alert_name in {"HighCPUPreScale", "KafkaLag"}
}

# Always allow in dry-run mode
allow if {
    input.dry_run == true
}
