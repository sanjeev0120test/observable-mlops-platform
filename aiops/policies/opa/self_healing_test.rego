package platform.self_healing_test

# OPA unit tests for self_healing.rego
# Run with: opa test aiops/policies/opa/ -v
# All tests must pass before any policy change is merged (see 00-pr-validate.yml)

# ─── ALLOW TESTS ──────────────────────────────────────────────────────────────

test_allow_restart_pod_crashloop_default_ns {
    allow with input as {
        "action": "restart_pod",
        "target": {"namespace": "default", "pod": "test-app-abc123"},
        "trigger": {"alert_name": "PodCrashLoopBackOff", "severity": "critical"},
        "dry_run": false,
    }
}

test_allow_restart_pod_oomkilled {
    allow with input as {
        "action": "restart_pod",
        "target": {"namespace": "ml-serving", "pod": "drift-monitor-xyz"},
        "trigger": {"alert_name": "PodOOMKilled", "severity": "warning"},
        "dry_run": false,
    }
}

test_allow_scale_deployment_high_cpu {
    allow with input as {
        "action": "scale_deployment",
        "target": {"namespace": "platform", "deployment": "anomaly-detector"},
        "trigger": {"alert_name": "HighCPUPreScale", "severity": "warning"},
        "dry_run": false,
    }
}

test_allow_scale_deployment_kafka_lag {
    allow with input as {
        "action": "scale_deployment",
        "target": {"namespace": "data-pipeline", "deployment": "kafka-consumer"},
        "trigger": {"alert_name": "KafkaLag", "severity": "warning"},
        "dry_run": false,
    }
}

test_allow_rollback_deployment_critical {
    allow with input as {
        "action": "rollback_deployment",
        "target": {"namespace": "ml-serving", "deployment": "pod-failure-prediction"},
        "trigger": {"alert_name": "MLModelDriftDetected", "severity": "critical"},
        "dry_run": false,
    }
}

test_allow_dry_run_requires_valid_action_and_trigger {
    # dry_run=true does NOT bypass action/trigger checks — must match a valid allow rule
    allow with input as {
        "action": "restart_pod",
        "target": {"namespace": "default", "pod": "test-pod"},
        "trigger": {"alert_name": "PodCrashLoopBackOff", "severity": "warning"},
        "dry_run": true,
    }
}

# ─── DENY TESTS ───────────────────────────────────────────────────────────────

test_deny_kube_system_any_action {
    not allow with input as {
        "action": "restart_pod",
        "target": {"namespace": "kube-system", "pod": "coredns-abc"},
        "trigger": {"alert_name": "PodCrashLoopBackOff", "severity": "critical"},
        "dry_run": false,
    }
}

test_deny_cert_manager_namespace {
    not allow with input as {
        "action": "restart_pod",
        "target": {"namespace": "cert-manager", "pod": "cert-manager-abc"},
        "trigger": {"alert_name": "PodCrashLoopBackOff", "severity": "critical"},
        "dry_run": false,
    }
}

test_deny_monitoring_namespace {
    not allow with input as {
        "action": "scale_deployment",
        "target": {"namespace": "monitoring", "deployment": "prometheus"},
        "trigger": {"alert_name": "HighCPUPreScale", "severity": "warning"},
        "dry_run": false,
    }
}

test_deny_drain_node_non_critical {
    not allow with input as {
        "action": "drain_node",
        "target": {"namespace": "default", "node": "worker-1"},
        "trigger": {"alert_name": "NodeHighMemory", "severity": "warning"},
        "dry_run": false,
    }
}

test_deny_rollback_non_critical {
    not allow with input as {
        "action": "rollback_deployment",
        "target": {"namespace": "ml-serving", "deployment": "pod-failure-prediction"},
        "trigger": {"alert_name": "MLModelDriftDetected", "severity": "warning"},
        "dry_run": false,
    }
}

test_deny_unknown_action {
    not allow with input as {
        "action": "delete_namespace",
        "target": {"namespace": "default"},
        "trigger": {"alert_name": "SomeAlert", "severity": "critical"},
        "dry_run": false,
    }
}

test_deny_dry_run_in_kube_system {
    # Critical: dry_run=true must NOT bypass namespace protection
    not allow with input as {
        "action": "restart_pod",
        "target": {"namespace": "kube-system", "pod": "coredns"},
        "trigger": {"alert_name": "PodCrashLoopBackOff", "severity": "critical"},
        "dry_run": true,
    }
}

test_deny_wrong_alert_for_restart_pod {
    # restart_pod only allowed for CrashLoopBackOff or OOMKilled — not arbitrary alerts
    not allow with input as {
        "action": "restart_pod",
        "target": {"namespace": "default", "pod": "test-pod"},
        "trigger": {"alert_name": "HighCPUPreScale", "severity": "warning"},
        "dry_run": false,
    }
}

# ─── DENY_REASONS TESTS ───────────────────────────────────────────────────────

test_deny_reasons_kube_system_contains_message {
    reasons := deny_reasons with input as {
        "action": "restart_pod",
        "target": {"namespace": "kube-system", "pod": "coredns"},
        "trigger": {"alert_name": "PodCrashLoopBackOff", "severity": "critical"},
        "dry_run": false,
    }
    count(reasons) > 0
}

test_deny_reasons_drain_node_non_critical_message {
    reasons := deny_reasons with input as {
        "action": "drain_node",
        "target": {"namespace": "default", "node": "worker-1"},
        "trigger": {"alert_name": "NodeHighMemory", "severity": "warning"},
        "dry_run": false,
    }
    count(reasons) > 0
}

test_deny_reasons_empty_for_valid_action {
    reasons := deny_reasons with input as {
        "action": "restart_pod",
        "target": {"namespace": "default", "pod": "test-pod"},
        "trigger": {"alert_name": "PodCrashLoopBackOff", "severity": "critical"},
        "dry_run": false,
    }
    count(reasons) == 0
}
