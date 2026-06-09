#!/usr/bin/env bash
# Collect all eval results and HTML reports, build the portal index page,
# then push to GitHub Pages (branch: gh-pages).
# Called by workflow 91-publish-portal.yml.

set -euo pipefail

PORTAL_DIR="portal/dist"
EVAL_DIR="eval-results"

mkdir -p "${PORTAL_DIR}"

echo "[publish-portal] Collecting eval results ..."
python3 - <<'PYEOF'
import json, os, sys
from pathlib import Path

eval_dir = Path("eval-results")
results = {}
if eval_dir.exists():
    for f in sorted(eval_dir.glob("uc*.json")):
        data = json.loads(f.read_text())
        results[data["uc"]] = data

passed = sum(1 for r in results.values() if r.get("passed"))
total = len(results)

rows = ""
for uc, r in sorted(results.items()):
    status = "PASS" if r.get("passed") else "FAIL"
    color = "#2ecc71" if r.get("passed") else "#e74c3c"
    rows += f"""
    <tr>
      <td><strong>{uc}</strong></td>
      <td style="color:{color};font-weight:bold">{status}</td>
      <td>{r.get('score', 'N/A')}</td>
      <td>{r.get('threshold', 'N/A')}</td>
    </tr>"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Observable MLOps Platform — Eval Dashboard</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }}
    h1 {{ color: #1a1a2e; }}
    .badge {{ display: inline-block; padding: 0.3em 0.8em; border-radius: 4px; color: white;
              background: #2ecc71; font-size: 1.1rem; }}
    .badge.fail {{ background: #e74c3c; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
    th {{ background: #1a1a2e; color: white; padding: 0.6rem 1rem; text-align: left; }}
    td {{ padding: 0.5rem 1rem; border-bottom: 1px solid #ddd; }}
    tr:hover {{ background: #f8f9fa; }}
  </style>
</head>
<body>
  <h1>Observable MLOps Platform</h1>
  <p>Enterprise AIOps + MLOps — 23 use cases, all CI-gated</p>
  <p>
    <span class="badge {'fail' if passed < total else ''}">
      {passed}/{total} UC Gates Passing
    </span>
  </p>
  <table>
    <thead><tr><th>Use Case</th><th>Status</th><th>Score</th><th>Threshold</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p><small>Generated at: {__import__('datetime').datetime.utcnow().isoformat()}Z</small></p>
</body>
</html>"""

Path("portal/dist/index.html").write_text(html)
print(f"[publish-portal] Portal built — {passed}/{total} UCs passing")
PYEOF

# Copy any drift/eval HTML reports
if ls services/drift-monitor/reports/*.html >/dev/null 2>&1; then
    cp services/drift-monitor/reports/*.html "${PORTAL_DIR}/"
    echo "[publish-portal] Copied drift reports."
fi

echo "[publish-portal] Portal ready at ${PORTAL_DIR}/"
ls -lh "${PORTAL_DIR}/"
