#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
campaign_root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
poll_seconds="${SPINE_REPORT_WATCH_SECONDS:-60}"
log_path="${SPINE_REPORT_WATCH_LOG:-${campaign_root}/formal_v6_report_watcher.log}"
audit_path="${repo}/docs/paper/data/formal_v6_primary/evidence_package_audit.json"

fingerprint() {
  python3 - "${campaign_root}" <<'PY'
from __future__ import annotations

import hashlib
from pathlib import Path
import sys


root = Path(sys.argv[1]).resolve()
result_roots = (
    root / "formal_v6_sssp_exact" / "runs",
    root / "formal_v6_cc_residual_priority" / "runs",
    root / "formal_v6_r19_sssp_warm" / "runs",
)
digest = hashlib.sha256()
paths = sorted(
    path.resolve()
    for result_root in result_roots
    if result_root.is_dir()
    for path in result_root.glob("runs/*/case_result.json")
)
for path in paths:
    digest.update(str(path.relative_to(root)).encode("ascii"))
    digest.update(b"\0")
    digest.update(hashlib.sha256(path.read_bytes()).digest())
print(f"{len(paths)}:{digest.hexdigest()}")
PY
}

mkdir -p "$(dirname "${log_path}")"
cd "${repo}"
last="$(fingerprint)"
printf '%s watcher_started fingerprint=%s\n' "$(date --iso-8601=seconds)" "${last}" \
  >> "${log_path}"

while true; do
  sleep "${poll_seconds}"
  current="$(fingerprint)"
  if [[ "${current}" == "${last}" ]]; then
    continue
  fi
  printf '%s evidence_changed old=%s new=%s\n' \
    "$(date --iso-8601=seconds)" "${last}" "${current}" >> "${log_path}"
  if bash scripts/refresh_formal_v6_report.sh >> "${log_path}" 2>&1; then
    last="${current}"
    printf '%s report_refresh_pass fingerprint=%s\n' \
      "$(date --iso-8601=seconds)" "${last}" >> "${log_path}"
  else
    printf '%s report_refresh_fail fingerprint=%s\n' \
      "$(date --iso-8601=seconds)" "${current}" >> "${log_path}"
    continue
  fi
  if [[ -s "${audit_path}" ]] &&
     jq -e '.full_matrix_status == "PASS"' "${audit_path}" >/dev/null; then
    printf '%s watcher_finished full_matrix_status=PASS\n' \
      "$(date --iso-8601=seconds)" >> "${log_path}"
    break
  fi
done
