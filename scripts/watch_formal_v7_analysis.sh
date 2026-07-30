#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
poll_seconds="${SPINE_V7_ANALYSIS_WATCH_SECONDS:-30}"
log_path="${SPINE_V7_ANALYSIS_WATCH_LOG:-${root}/formal_v7_analysis_watcher.log}"

fingerprint() {
  python3 - "${root}" <<'PY'
from __future__ import annotations

import hashlib
from pathlib import Path
import sys


root = Path(sys.argv[1]).resolve()
result_roots = (
    root / "formal_v6_sssp_exact" / "runs",
    root / "formal_v6_cc_residual_priority" / "runs",
    root / "formal_v6_r19_sssp_warm" / "runs",
    root / "formal_v7_orkut_spine_sssp" / "runs",
    root / "formal_v7_stack_spine_cc" / "runs",
    root / "formal_v7_pokec_spine_sssp_sidecar" / "runs",
    root / "formal_v7_hot_transition_successors" / "runs",
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
bash scripts/analyze_formal_v7_primary.sh >> "${log_path}" 2>&1
last="$(fingerprint)"
printf '%s watcher_started fingerprint=%s\n' \
  "$(date --iso-8601=seconds)" "${last}" >> "${log_path}"

while true; do
  sleep "${poll_seconds}"
  current="$(fingerprint)"
  if [[ "${current}" == "${last}" ]]; then
    continue
  fi
  printf '%s evidence_changed old=%s new=%s\n' \
    "$(date --iso-8601=seconds)" "${last}" "${current}" >> "${log_path}"
  if bash scripts/refresh_formal_v7_report.sh >> "${log_path}" 2>&1; then
    last="${current}"
    printf '%s report_refresh_pass fingerprint=%s\n' \
      "$(date --iso-8601=seconds)" "${last}" >> "${log_path}"
  else
    printf '%s report_refresh_fail fingerprint=%s\n' \
      "$(date --iso-8601=seconds)" "${current}" >> "${log_path}"
  fi
done
