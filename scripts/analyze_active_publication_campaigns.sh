#!/usr/bin/env bash
set -euo pipefail

campaign_root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
output_dir="${SPINE_LIVE_ANALYSIS_DIR:-${campaign_root}/live_publication_analysis}"

result_roots=(
  noncapacity_v3_repair
  fullgraph_v2_repair
  formal_v3_weighted_wave
  formal_v3_wiki_cc_k1
  formal_v3_superuser_weighted
  formal_v3_superuser_spine_fullpr
  formal_v3_au_grasu_nonmonotonic
  formal_v3_au_spine_weight_remaining
  formal_v3_au_insert_endpoints
  formal_v3_r19_spine
  formal_v3_r19_grasu_fullpr
  formal_v3_small_cc_residual
)

manifest_roots=(
  fullgraph_v2_repair
  formal_v3_weighted_wave
  formal_v3_wiki_cc_k1
  formal_v3_superuser_weighted
  formal_v3_superuser_spine_fullpr
  formal_v3_au_grasu_nonmonotonic
  formal_v3_au_spine_weight_remaining
  formal_v3_au_insert_endpoints
  formal_v3_r19_spine
  formal_v3_r19_grasu_fullpr
  formal_v3_small_cc_residual
)

command=(
  python3 scripts/analyze_publication_experiment_campaign.py
  --out-dir "${output_dir}"
)
for root in "${result_roots[@]}"; do
  command+=(--result-root "${campaign_root}/${root}")
done
for root in "${manifest_roots[@]}"; do
  command+=(--manifest "${campaign_root}/${root}/campaign_manifest.json")
done

"${command[@]}"
