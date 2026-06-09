package platform.self_healing

# Classic Rego syntax - no future.keywords imports needed.
# Tested with OPA v0.65.0.

default allow = false

# Allow restart_pod for CrashLoopBackOff in non-protected namespaces
allow {
    input.action == "restart_pod"
    input.trigger.alert_name == "PodCrashLoopBackOff"
    input.target.namespace != "kube-system"
    input.target.namespace != "cert-manager"
    input.target.namespace != "kyverno"
    input.target.namespace != "keda"
}

# Allow scale_deployment for KEDA-triggered alerts in non-protected namespaces
allow {
    input.action == "scale_deployment"
    input.trigger.alert_name == "HighCPUPreScale"
    input.target.namespace != "kube-system"
    input.target.namespace != "cert-manager"
    input.target.namespace != "kyverno"
    input.target.namespace != "keda"
}

allow {
    input.action == "scale_deployment"
    input.trigger.alert_name == "KafkaLag"
    input.target.namespace != "kube-system"
    input.target.namespace != "cert-manager"
    input.target.namespace != "kyverno"
    input.target.namespace != "keda"
}

# Allow dry-run testing in non-protected namespaces
allow {
    input.dry_run == true
    input.target.namespace != "kube-system"
    input.target.namespace != "cert-manager"
    input.target.namespace != "kyverno"
    input.target.namespace != "keda"
}

# deny_reasons partial set (audit/reporting)
deny_reasons[reason] {
    input.action == "drain_node"
    input.trigger.severity != "critical"
    reason := "action 'drain_node' requires critical severity"
}

deny_reasons[reason] {
    input.action == "rollback_deployment"
    input.trigger.severity != "critical"
    reason := "action 'rollback_deployment' requires critical severity"
}

deny_reasons[reason] {
    input.target.namespace == "kube-system"
    reason := "namespace 'kube-system' is protected"
}

deny_reasons[reason] {
    input.target.namespace == "cert-manager"
    reason := "namespace 'cert-manager' is protected"
}

deny_reasons[reason] {
    input.target.namespace == "kyverno"
    reason := "namespace 'kyverno' is protected"
}

deny_reasons[reason] {
    input.target.namespace == "keda"
    reason := "namespace 'keda' is protected"
}
