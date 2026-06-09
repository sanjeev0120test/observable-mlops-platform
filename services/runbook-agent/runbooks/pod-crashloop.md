# Runbook: Pod CrashLoopBackOff

**UC8 — RAG Runbook Agent knowledge base**

## Symptoms
- Pod restart count > 5 in 5 minutes
- `kubectl describe pod` shows `Back-off restarting failed container`
- Logs show `exit code 1` or OOMKilled

## Root Causes

### 1. OOMKilled (Memory limit exceeded)
- Check: `kubectl describe pod <pod> | grep -A5 OOMKilled`
- Fix: Increase `resources.limits.memory` in Deployment manifest

### 2. Application crash on startup
- Check: `kubectl logs <pod> --previous` for startup error
- Common causes: Missing environment variable, DB connection refused, missing secret
- Fix: Check `envFrom` + `env` in pod spec; verify Secret/ConfigMap exists

### 3. Readiness probe failing
- Check: `kubectl describe pod <pod> | grep "Readiness probe"`
- Fix: Increase `initialDelaySeconds`, verify probe endpoint returns 200

### 4. Image pull failure / wrong tag
- Check: `kubectl describe pod <pod> | grep "image"`
- Fix: Correct image tag in Deployment spec; check registry credentials

## Automated Remediation (UC6)
The self-healing service will auto-restart the pod if:
- Restart count > 5 AND severity = critical
- OPA policy `platform.self_healing.allow` returns true
- Namespace is not protected (kube-system, cert-manager, etc.)

## Escalation
If auto-remediation fails after 3 attempts, page on-call via PagerDuty and create post-mortem (UC23).
