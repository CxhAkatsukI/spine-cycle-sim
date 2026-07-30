#!/usr/bin/env bash
set -euo pipefail

campaign_root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
interval_seconds="${SPINE_MONITOR_INTERVAL_SECONDS:-60}"
once=0

if [[ "${1:-}" == "--once" ]]; then
  once=1
elif [[ $# -ne 0 ]]; then
  echo "usage: $0 [--once]" >&2
  exit 2
fi

campaigns=(
  fullgraph_v2_repair
  formal_v3_weighted_wave
  formal_v3_wiki_cc_k1
  formal_v3_superuser_weighted
  formal_v3_superuser_spine_fullpr
  formal_v3_au_grasu_nonmonotonic
  formal_v3_au_spine_weight_remaining
  formal_v3_au_spine_weight_u1
  formal_v3_au_spine_delete
  formal_v3_au_insert_endpoints
  formal_v3_au_dense_k4
  formal_v3_remaining5_spine_weighted
  formal_v3_remaining7_k4_weighted
  formal_v3_r19_spine
  formal_v3_r19_grasu_fullpr
  formal_v3_r19_k4_priority
  formal_v3_r19_cc_guard
  formal_v3_stackoverflow_spine
  formal_v4_stackoverflow_spine_linear
  formal_v3_small_cc_residual
  formal_v3_small_fullpr
)

while true; do
  date -Is
  current_available_bytes="$(
    awk '$1 == "MemAvailable:" { print $2 * 1024 }' /proc/meminfo
  )"
  for campaign in "${campaigns[@]}"; do
    state="${campaign_root}/${campaign}/run/campaign_state.json"
    if [[ ! -f "${state}" ]]; then
      state="${campaign_root}/${campaign}/campaign_state.json"
    fi
    if [[ ! -f "${state}" ]]; then
      printf '%-38s missing\n' "${campaign}"
      continue
    fi
    repaired=0
    while IFS= read -r job_id; do
      [[ -n "${job_id}" ]] || continue
      execution_id="${job_id##*.}"
      result="${campaign_root}/${campaign}/runs/${execution_id}/case_result.json"
      if [[ -f "${result}" ]] && jq -e '
        .status == "pass"
        and (.admission.reused_child // false)
      ' "${result}" >/dev/null 2>&1; then
        ((repaired += 1))
      fi
    done < <(
      jq -r '.jobs[] | select(.status == "fail") | .job_id' "${state}"
    )
    jq -r \
      --arg campaign "${campaign}" \
      --argjson repaired "${repaired}" \
      --argjson current_available_bytes "${current_available_bytes}" '
      (.summary.by_status.fail // 0) as $failed |
      [
        $campaign,
        .status,
        ("pass=" + ((.summary.by_status.pass // 0) | tostring)),
        ("run=" + ((.summary.by_status.running // 0) | tostring)),
        ("queue=" + ((.summary.by_status.queued // 0) | tostring)),
        ("fail=" + ($failed | tostring)),
        ("repair=" + ($repaired | tostring)),
        ("unresolved_fail=" + (($failed - $repaired) | tostring)),
        ("stop=" + ((.summary.by_status.stopped // 0) | tostring)),
        ("rss_gib=" + (((if .status == "running" then (.host.campaign_rss_bytes // 0) else 0 end) / 1073741824 * 10 | floor) / 10 | tostring)),
        ("available_gib=" + (($current_available_bytes / 1073741824) | floor | tostring)),
        ("breaker=" + (if (.host.memory_pressure_active // false) then "active" else "clear" end))
      ] | @tsv
    ' "${state}"
  done
  free -h | sed -n '1,2p'
  printf '\n'
  if (( once )); then
    break
  fi
  sleep "${interval_seconds}"
done
