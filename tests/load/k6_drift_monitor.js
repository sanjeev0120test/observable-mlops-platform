/**
 * k6 Load Test: Drift Monitor Service (UC1)
 * Tests /api/v1/check-drift under sustained load.
 *
 * Target SLOs:
 *   - P99 latency < 2000ms
 *   - P95 latency < 1000ms
 *   - Error rate < 1%
 *
 * Run:
 *   k6 run tests/load/k6_drift_monitor.js
 *   k6 run --env BASE_URL=http://localhost:8002 tests/load/k6_drift_monitor.js
 *
 * Output: k6 HTML report + InfluxDB push (optional)
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";
import { textSummary } from "https://jslib.k6.io/k6-summary/0.0.2/index.js";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8002";

// Custom metrics
const errorRate = new Rate("drift_check_error_rate");
const driftLatency = new Trend("drift_check_latency_ms", true);
const retriggeredCounter = new Counter("retrain_triggered_total");

export const options = {
  scenarios: {
    // Stage 1: Warm-up (2 min)
    warmup: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "1m", target: 5 },
        { duration: "1m", target: 10 },
      ],
      gracefulRampDown: "30s",
    },
    // Stage 2: Sustained load (5 min at 20 VUs)
    sustained: {
      executor: "constant-vus",
      vus: 20,
      duration: "5m",
      startTime: "2m",
      gracefulStop: "30s",
    },
    // Stage 3: Spike test (30s burst to 100 VUs)
    spike: {
      executor: "ramping-vus",
      startTime: "8m",
      stages: [
        { duration: "30s", target: 100 },
        { duration: "1m", target: 100 },
        { duration: "30s", target: 0 },
      ],
    },
  },
  thresholds: {
    // SLO gates — fail the load test if violated
    "http_req_duration{scenario:sustained}": ["p(99)<2000", "p(95)<1000"],
    drift_check_error_rate: ["rate<0.01"], // < 1% error rate
    http_req_failed: ["rate<0.01"],
  },
};

const MODELS = [
  "pod-failure-prediction",
  "log-anomaly-detector",
  "cost-anomaly-detector",
];

export default function () {
  const model = MODELS[Math.floor(Math.random() * MODELS.length)];

  const payload = JSON.stringify({
    model_name: model,
    reference_dataset: "data/synthetic/pod_metrics.parquet",
    current_dataset: "data/synthetic/pod_metrics.parquet",
    primary_feature: "cpu_usage_pct",
  });

  const params = {
    headers: { "Content-Type": "application/json" },
    timeout: "10s",
  };

  const start = Date.now();
  const res = http.post(`${BASE_URL}/api/v1/check-drift`, payload, params);
  const latency = Date.now() - start;

  driftLatency.add(latency);

  const ok = check(res, {
    "status is 200": (r) => r.status === 200,
    "response has psi_score": (r) => {
      try {
        return JSON.parse(r.body).psi_score !== undefined;
      } catch {
        return false;
      }
    },
    "latency < 2000ms": () => latency < 2000,
  });

  errorRate.add(!ok);

  if (res.status === 200) {
    try {
      const body = JSON.parse(res.body);
      if (body.retrain_triggered) {
        retriggeredCounter.add(1);
      }
    } catch {}
  }

  sleep(0.5 + Math.random() * 0.5); // 0.5-1.0s think time
}

export function handleSummary(data) {
  return {
    stdout: textSummary(data, { indent: " ", enableColors: true }),
    "tests/load/results/drift_monitor_load_test.json": JSON.stringify(data, null, 2),
  };
}
