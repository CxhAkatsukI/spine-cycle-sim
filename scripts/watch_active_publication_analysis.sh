#!/usr/bin/env bash
set -euo pipefail

interval_seconds="${SPINE_ANALYSIS_INTERVAL_SECONDS:-300}"
campaign_root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
log_path="${SPINE_LIVE_ANALYSIS_LOG:-${campaign_root}/live_analysis.log}"

while true; do
  {
    date -Is
    scripts/analyze_active_publication_campaigns.sh
  } >>"${log_path}" 2>&1
  sleep "${interval_seconds}"
done
