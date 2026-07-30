#!/usr/bin/env bash
set -euo pipefail

root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
for campaign in formal_v6_sssp_exact formal_v6_cc_residual_priority; do
  run_dir="${root}/${campaign}/run"
  if [[ -f "${run_dir}/campaign_state.json" ]]; then
    printf '\n=== %s ===\n' "${campaign}"
    python3 scripts/monitor_large_graph_campaign.py \
      --run-dir "${run_dir}" --max-rows 30
  fi
done

printf '\n=== host memory ===\n'
free -h
