# Runbook: High CPU — Pre-emptive Scaling

**UC4 + UC8 — Predictive scaling runbook**

## Symptoms
- CPU usage > 70% for 5+ minutes
- p99 latency degrading
- `HighCPUPreScale` alert firing

## Root Causes

### 1. Legitimate traffic spike (expected)
- Check: Grafana dashboard → HTTP traffic panel (diurnal pattern)
- Action: Allow KEDA ScaledObject to scale out — no manual intervention needed

### 2. Runaway process / loop
- Check: `kubectl top pod -n <namespace>` — identify specific pod
- Fix: Rolling restart the deployment

### 3. ML model inference spike (UC9)
- Check: `ml-serving-api` CPU + request rate
- Fix: KServe canary rollback if new model version is the cause

## Automated Response (UC4)
Prophet forecast detects load increase 5+ minutes in advance and pre-creates KEDA ScaledObject.
KEDA scales pods before latency degrades.

## KEDA ScaledObject Reference
```yaml
triggers:
  - type: prometheus
    metadata:
      serverAddress: http://prometheus:9090
      metricName: http_requests_per_second
      threshold: "100"
      query: sum(rate(http_requests_total[2m]))
```
