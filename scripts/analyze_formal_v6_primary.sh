#!/usr/bin/env bash
set -euo pipefail

root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
output_dir="${SPINE_V6_PRIMARY_ANALYSIS_DIR:-${root}/formal_v6_primary_analysis}"
sssp="${root}/formal_v6_sssp_exact"
cc_residual="${root}/formal_v6_cc_residual_priority"
r19="${root}/formal_v6_r19_sssp_warm"

python3 scripts/analyze_publication_experiment_campaign.py \
  --result-root "${sssp}/runs" \
  --result-root "${cc_residual}/runs" \
  --result-root "${r19}/runs" \
  --manifest "${sssp}/campaign_manifest.json" \
  --manifest "${cc_residual}/campaign_manifest.json" \
  --manifest "${r19}/campaign_manifest.json" \
  --required-system spine \
  --required-system grasu_regraph_k4_shared \
  --result-transition-contract configs/contracts/large_graph_publication_campaign_fullgraph_v6.json \
  --out-dir "${output_dir}"
