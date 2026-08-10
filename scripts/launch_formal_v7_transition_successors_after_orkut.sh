#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
orkut_state="${root}/formal_v7_orkut_spine_sssp/run/campaign_state.json"
campaign="${root}/formal_v7_hot_transition_successors"
manifest="${campaign}/campaign_manifest.json"
run_dir="${campaign}/run"
poll_seconds="${SPINE_V7_SUCCESSOR_POLL_SECONDS:-30}"

cd "${repo}"
while true; do
  if [[ ! -s "${orkut_state}" ]]; then
    sleep "${poll_seconds}"
    continue
  fi
  status="$(jq -r '.jobs[0].status // "missing"' "${orkut_state}")"
  case "${status}" in
    pass)
      break
      ;;
    fail|stopped|blocked)
      printf 'Orkut v7 prerequisite ended with status=%s; successors not launched\n' \
        "${status}" >&2
      exit 3
      ;;
    queued|running|missing)
      sleep "${poll_seconds}"
      ;;
    *)
      printf 'unknown Orkut v7 status: %s\n' "${status}" >&2
      exit 4
      ;;
  esac
done

if [[ ! -s "${manifest}" ]]; then
  python3 scripts/generate_publication_experiment_campaign.py \
    --contract configs/contracts/large_graph_publication_campaign_fullgraph_v7.json \
    --materialization-root "${root}" \
    --output-root "${campaign}/runs" \
    --manifest "${manifest}" \
    --python /usr/bin/python3 \
    --sst /data/feiyang/sst/bin/sst \
    --lib-dir /data/tmp/chuxiao/spine-skip-fit-hot-native-20260730 \
    --capability-catalog \
      configs/contracts/grasu_regraph_full_graph_capabilities_v7.json \
    --tier main_e2e \
    --dataset hollywood_2009 \
    --dataset ljournal_2008 \
    --algorithm weighted_sssp \
    --system spine \
    --scenario insert \
    --batch-size 8 \
    --source-cohort median_degree \
    --max-cycles 10000000000000
fi

resume=()
if [[ -s "${run_dir}/campaign_state.json" ]]; then
  resume=(--resume)
fi
exec python3 scripts/run_large_graph_campaign.py \
  --manifest "${manifest}" \
  --run-dir "${run_dir}" \
  --jobs 1 \
  --large-jobs 1 \
  --memory-reserve-gib 64 \
  --memory-emergency-gib 48 \
  --memory-recovery-gib 64 \
  --max-starts-per-sample 1 \
  --sample-seconds 5 \
  --no-progress-warn-minutes 15 \
  --cpu-offset 10 \
  "${resume[@]}"
