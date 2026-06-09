package platform.self_healing

import future.keywords.contains
import future.keywords.if

# OPA policy: Gate every autonomous remediation action.
# Uses explicit != comparisons — no negation helpers, no set-literal membership.
# Protected namespaces are NEVER touched by automation.

default allow := false

# Allow restart_pod for CrashLoopBackOff only in non-protected namespaces
allow if {
    input.action == "restart_pod"
    input.trigger.alert_name == "PodCrashLoopBackOff"
    input.target.namespace != "kube-system"
    input.target.namespace != "cert-manager"
    input.target.namespace != "kyverno"
    input.target.namespace != "keda"
}

# Allow scale_deployment for HighCPUPreScale in non-protected namespaces
allow if {
    input.action == "scale_deployment"
    input.trigger.alert_name == "HighCPUPreScale"
    input.target.namespace != "kube-system"
    input.target.namespace != "cert-manager"
    input.target.namespace != "kyverno"
    input.target.namespace != "keda"
}

# Allow scale_deployment for KafkaLag in non-protected namespaces
allow if {
    input.action == "scale_deployment"
    input.trigger.alert_name == "KafkaLag"
    input.target.namespace != "kube-system"
    input.target.namespace != "cert-manager"
    input.target.namespace != "kyverno"
    input.target.namespace != "keda"
}

# Allow dry-run testing in non-protected namespaces only
allow if {
    input.dry_run == true
    input.target.namespace != "kube-system"
    input.target.namespace != "cert-manager"
    input.target.namespace != "kyverno"
    input.target.namespace != "keda"
}

# ---- deny_reasons (audit / reporting only) ----

deny_reasons contains "action 'drain_node' requires critical severity" if {
    input.action == "drain_node"
    input.trigger.severity != "critical"
}

deny_reasons contains "action 'rollback_deployment' requires critical severity" if {
    input.action == "rollback_deployment"
    input.trigger.severity != "critical"
}

deny_reasons contains "namespace 'kube-system' is protected" if {
    input.target.namespace == "kube-system"
}

deny_reasons contains "namespace 'cert-manager' is protected" if {
    input.target.namespace == "cert-manager"
}

deny_reasons contains "namespace 'kyverno' is protected" if {
    input.target.namespace == "kyverno"
}

deny_reasons contains "namespace 'keda' is protected" if {
    input.target.namespace == "keda"
}
