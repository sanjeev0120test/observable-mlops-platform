/**
 * k6 Load Test: Self-Healing Service (UC6)
 * Tests /api/v1/remediate under concurrent remediation requests.
 *
 * Key validation: verify OPA policy gate holds under load
 * (no remediation should bypass policy even at high concurrency)
 *
 * Run: k6 run tests/load/k6_self_healing.js
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Counter } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8005";

const errorRate = new Rate("remediation_error_rate");
const allowedActions = new Counter("remediation_allowed_total");
const deniedActions = new Counter("remediation_denied_total");
const opaUnavailable = new Counter("opa_unavailable_503_total");

export const options = {
  scenarios: {
    sustained: {
      executor: "constant-vus",
      vus: 10,
      duration: "3m",
    },
  },
  thresholds: {
    "http_req_duration": ["p(99)<3000", "p(95)<1500"],
    remediation_error_rate: ["rate<0.05"],
    // Critical: OPA should NEVER be unavailable during normal load
    "opa_unavailable_503_total": ["count<5"],
  },
};

const VALID_REQUESTS = [
  {
    action: "restart_pod",
    target: { namespace: "default", pod: "test-pod-abc123" },
    trigger: { alert_name: "PodCrashLoopBackOff", severity: "critical" },
    dry_run: true,
  },
  {
    action: "scale_deployment",
    target: { namespace: "platform", deployment: "anomaly-detector" },
    trigger: { alert_name: "HighCPUPreScale", severity: "warning" },
    dry_run: true,
  },
];

const INVALID_REQUESTS = [
  {
    // Protected namespace — must always be denied
    action: "restart_pod",
    target: { namespace: "kube-system", pod: "coredns" },
    trigger: { alert_name: "PodCrashLoopBackOff", severity: "critical" },
    dry_run: true,
  },
  {
    // Unknown action — must return 400
    action: "delete_namespace",
    target: { namespace: "default" },
    trigger: {},
    dry_run: true,
  },
];

export default function () {
  // Mix valid and invalid requests
  const isInvalid = Math.random() < 0.3;
  const pool = isInvalid ? INVALID_REQUESTS : VALID_REQUESTS;
  const req = pool[Math.floor(Math.random() * pool.length)];

  const params = {
    headers: { "Content-Type": "application/json" },
    timeout: "15s",
  };

  const res = http.post(
    `${BASE_URL}/api/v1/remediate`,
    JSON.stringify(req),
    params
  );

  if (res.status === 503) {
    opaUnavailable.add(1);
  }

  const ok = check(res, {
    "not a 500": (r) => r.status !== 500,
    "valid action has JSON response": (r) => {
      if (r.status !== 200) return true; // 400/503 ok for invalid requests
      try {
        const b = JSON.parse(r.body);
        return b.allowed !== undefined && b.executed !== undefined;
      } catch {
        return false;
      }
    },
    "protected namespace is denied": (r) => {
      if (req.target?.namespace === "kube-system" && r.status === 200) {
        try {
          return JSON.parse(r.body).allowed === false;
        } catch {
          return false;
        }
      }
      return true;
    },
  });

  errorRate.add(!ok);

  if (res.status === 200) {
    try {
      const body = JSON.parse(res.body);
      if (body.allowed) allowedActions.add(1);
      else deniedActions.add(1);
    } catch {}
  }

  sleep(0.2 + Math.random() * 0.3);
}
