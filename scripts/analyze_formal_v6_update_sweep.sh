#!/usr/bin/env bash
set -euo pipefail

root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
output_dir="${SPINE_V6_UPDATE_ANALYSIS_DIR:-${root}/formal_v6_au_update_analysis}"

python3 scripts/analyze_publication_experiment_campaign.py \
  --system-result-root spine \
    "${root}/formal_v6_au_spine_updates_default/runs" \
  --system-result-root grasu_regraph_k1 \
    "${root}/formal_v3_weighted_wave" \
  --system-result-root grasu_regraph_k4_shared \
    "${root}/formal_v3_weighted_wave" \
  --system-result-root grasu_regraph_k1 \
    "${root}/formal_v3_au_insert_endpoints" \
  --system-result-root grasu_regraph_k4_shared \
    "${root}/formal_v3_au_insert_endpoints" \
  --system-result-root grasu_regraph_k1 \
    "${root}/formal_v3_au_grasu_nonmonotonic" \
  --system-result-root grasu_regraph_k4_shared \
    "${root}/formal_v3_au_grasu_nonmonotonic" \
  --manifest "${root}/formal_v6_au_spine_updates_default/campaign_manifest.json" \
  --manifest "${root}/formal_v3_weighted_wave/campaign_manifest.json" \
  --manifest "${root}/formal_v3_au_insert_endpoints/campaign_manifest.json" \
  --manifest "${root}/formal_v3_au_grasu_nonmonotonic/campaign_manifest.json" \
  --result-transition-contract \
    configs/contracts/large_graph_publication_campaign_fullgraph_v6.json \
  --out-dir "${output_dir}"
