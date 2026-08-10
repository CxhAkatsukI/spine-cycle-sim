#!/usr/bin/env bash
set -euo pipefail

root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
campaign="${SPINE_V8_UPDATE_SCALING_ROOT:-${root}/formal_v8_au_update_scaling}"
output_dir="${SPINE_V8_UPDATE_SCALING_ANALYSIS_DIR:-${campaign}/analysis}"

args=()
for system in spine grasu_regraph_k4_shared; do
  for batch in 64 1024 16384 131072; do
    args+=(--result-root "${campaign}/runs_update_only/${system}_u${batch}")
  done
done

python3 scripts/analyze_publication_experiment_campaign.py \
  "${args[@]}" \
  --required-system spine \
  --required-system grasu_regraph_k4_shared \
  --require-complete \
  --out-dir "${output_dir}"
