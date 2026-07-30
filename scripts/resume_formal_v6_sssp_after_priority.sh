#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
campaign_root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
main="${campaign_root}/formal_v6_sssp_exact"
priority="${campaign_root}/formal_v6_cc_residual_priority"
pokec_sidecar="${campaign_root}/formal_v6_pokec_sssp_k4_sidecar"
pokec_job="run.soc_pokec.weighted_sssp.insert.u8.grasu_regraph_k4_shared.bb8611a68e5fdcd8b898"
cc_job="run.sx_stackoverflow.connected_components.insert.u8.grasu_regraph_k4_shared.40d4283eb14d3fefe31f"
residual_job="run.sx_stackoverflow.thresholded_residual_pagerank.insert.u8.grasu_regraph_k4_shared.b841b79faa2aace92be3"

cd "${repo}"

launcher_pid="$(jq -r '.launcher_pid // 0' "${main}/run/campaign_state.json")"
if [[ "${launcher_pid}" != "0" ]] && kill -0 "${launcher_pid}" 2>/dev/null; then
  printf 'formal_v6_sssp_exact launcher is still active (pid=%s)\n' "${launcher_pid}" >&2
  exit 2
fi

pokec_status="$(jq -r '.status // "missing"' "${pokec_sidecar}/run/campaign_state.json")"
if [[ "${pokec_status}" != "pass" ]]; then
  printf 'Pokec K4 sidecar is not complete: %s\n' "${pokec_status}" >&2
  exit 2
fi
if [[ ! -s "${main}/runs/runs/bb8611a68e5fdcd8b898/case_result.json" ]]; then
  printf 'Pokec sidecar result is missing from the canonical result root\n' >&2
  exit 2
fi

priority_passes="$(
  jq \
    --arg cc "${cc_job}" \
    --arg residual "${residual_job}" \
    '[.jobs[] | select(.job_id == $cc or .job_id == $residual) | select(.status == "pass")] | length' \
    "${priority}/run/campaign_state.json"
)"
if [[ "${priority_passes}" != "2" ]]; then
  printf 'StackOverflow K4 CC/residual priority pair is not complete (%s/2)\n' \
    "${priority_passes}" >&2
  exit 2
fi

# Campaign resume requeues every non-PASS state. The control file is consumed
# before the first launch decision, preventing duplicate execution of Pokec.
python3 scripts/control_large_graph_campaign.py \
  --run-dir "${main}/run" \
  stop "${pokec_job}" \
  --reason 'canonical Pokec result completed by the dedicated sidecar; suppress duplicate execution on resume'

exec python3 scripts/run_large_graph_campaign.py \
  --manifest "${main}/campaign_manifest.json" \
  --run-dir "${main}/run" \
  --jobs 4 \
  --large-jobs 2 \
  --memory-reserve-gib 64 \
  --memory-emergency-gib 48 \
  --memory-recovery-gib 64 \
  --max-starts-per-sample 2 \
  --sample-seconds 5 \
  --no-progress-warn-minutes 15 \
  --cpu-offset 0 \
  --no-pin-cpus \
  --resume
