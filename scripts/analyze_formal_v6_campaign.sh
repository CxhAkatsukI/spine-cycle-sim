#!/usr/bin/env bash
set -euo pipefail

campaign_dir="${SPINE_V6_CAMPAIGN_DIR:-/data/tmp/chuxiao/large_graph_campaign_v1/formal_v6_sssp_exact}"
output_dir="${SPINE_V6_ANALYSIS_DIR:-${campaign_dir}/analysis}"

python3 scripts/analyze_publication_experiment_campaign.py \
  --result-root "${campaign_dir}/runs" \
  --manifest "${campaign_dir}/campaign_manifest.json" \
  --result-transition-contract configs/contracts/large_graph_publication_campaign_fullgraph_v6.json \
  --out-dir "${output_dir}"
