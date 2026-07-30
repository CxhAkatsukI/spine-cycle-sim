#!/usr/bin/env bash
set -euo pipefail

root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
output_dir="${SPINE_V7_PRIMARY_ANALYSIS_DIR:-${root}/formal_v7_primary_analysis}"

args=(
  --result-root "${root}/formal_v6_sssp_exact/runs"
  --result-root "${root}/formal_v6_cc_residual_priority/runs"
  --result-root "${root}/formal_v6_r19_sssp_warm/runs"
  --result-root "${root}/formal_v7_orkut_spine_sssp/runs"
  --result-root "${root}/formal_v7_stack_spine_cc/runs"
  --result-root "${root}/formal_v7_pokec_spine_sssp_sidecar/runs"
  --result-root "${root}/formal_v7_livejournal_spine_sssp_sidecar/runs"
  --result-root "${root}/formal_v7_hot_transition_successors/runs"
  --manifest "${root}/formal_v6_sssp_exact/campaign_manifest.json"
  --manifest "${root}/formal_v6_cc_residual_priority/campaign_manifest.json"
  --manifest "${root}/formal_v6_r19_sssp_warm/campaign_manifest.json"
  --manifest "${root}/formal_v7_orkut_spine_sssp/campaign_manifest.json"
  --manifest "${root}/formal_v7_stack_spine_cc/campaign_manifest.json"
  --manifest "${root}/formal_v7_pokec_spine_sssp_sidecar/campaign_manifest.json"
  --manifest "${root}/formal_v7_livejournal_spine_sssp_sidecar/campaign_manifest.json"
  --manifest "${root}/formal_v7_hot_transition_successors/campaign_manifest.json"
  --required-system spine
  --required-system grasu_regraph_k4_shared
  --result-transition-contract \
    configs/contracts/large_graph_publication_campaign_fullgraph_v7.json
  --out-dir "${output_dir}"
)

python3 scripts/analyze_publication_experiment_campaign.py "${args[@]}"
