#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plot_python="${SPINE_PLOT_PYTHON:-/data/tmp/chuxiao/spine-paper-plot-venv/bin/python}"
source_date_epoch="${SOURCE_DATE_EPOCH:-1785369600}"
data="${root}/docs/paper/data/formal_v7_primary"
analysis="/data/tmp/chuxiao/large_graph_campaign_v1/formal_v7_primary_analysis"
rq3_analysis="/data/tmp/chuxiao/large_graph_campaign_v1/rq3_live"

if [[ ! -x "${plot_python}" ]]; then
  printf 'plot Python is not executable: %s\n' "${plot_python}" >&2
  exit 2
fi

cd "${root}"
bash scripts/analyze_formal_v7_primary.sh
bash scripts/analyze_formal_v6_update_sweep.sh
SPINE_RQ3_OUTPUT_DIR="${rq3_analysis}" bash scripts/analyze_active_rq3.sh
"${plot_python}" scripts/render_rq3_realized_work.py \
  --analysis-dir "${rq3_analysis}" \
  --figure-dir docs/figures \
  --data-dir docs/paper/data/rq3
python3 scripts/analyze_workload_component_energy.py \
  --system-rows "${analysis}/system_rows.csv" \
  --activity-rows "${analysis}/component_activity_rows.csv" \
  --power-rows docs/paper/data/component_power.csv \
  --out-dir docs/paper/data/workload_energy
"${plot_python}" scripts/render_formal_v6_primary.py \
  --analysis-dir "${analysis}" \
  --contract configs/contracts/large_graph_publication_campaign_fullgraph_v7.json \
  --data-dir "${data}" \
  --tex docs/paper/formal_v7_primary_results.tex \
  --report-version v7 \
  --artifact-prefix formal_v7
SOURCE_DATE_EPOCH="${source_date_epoch}" FORCE_SOURCE_DATE=1 \
  latexmk -pdf -interaction=nonstopmode -halt-on-error -cd \
    docs/paper/formal_v7_primary_results.tex
SOURCE_DATE_EPOCH="${source_date_epoch}" FORCE_SOURCE_DATE=1 \
  latexmk -c -cd docs/paper/formal_v7_primary_results.tex
python3 scripts/audit_formal_v6_evidence_package.py \
  --audit-id formal_v7_first_evidence_package_v1 \
  --primary-summary "${data}/summary.json" \
  --system-rows "${data}/system_rows.csv" \
  --pair-rows "${data}/pairs.csv" \
  --correctness-rows "${data}/correctness_groups.csv" \
  --component-rows "${data}/component_activity.csv" \
  --update-rows "${data}/update_pairs.csv" \
  --rq3-summary docs/paper/data/rq3/rq3_summary.json \
  --rq3-e2e-metrics docs/paper/data/rq3/rq3_e2e_metric_rows.csv \
  --out "${data}/evidence_package_audit.json" \
  --artifact docs/paper/formal_v7_primary_results.pdf \
  --artifact docs/evidence/formal_v6_r19_k4_preflight_20260730.json \
  --artifact docs/evidence/formal_v6_large_sssp_runtime_projection_20260730.json \
  --artifact docs/evidence/formal_v7_stopped_prefix_lower_bounds_20260731.json \
  --artifact docs/paper/data/formal_v7_primary/wall_time_feasibility.json \
  --artifact docs/paper/data/formal_v7_primary/superseded_results.csv \
  --artifact docs/paper/data/formal_v7_primary/all_spine_e2e.csv \
  --artifact docs/figures/formal_v7_all_spine_e2e.svg \
  --artifact docs/figures/formal_v7_primary_ratios.svg \
  --artifact docs/figures/formal_v7_memory_locality.svg \
  --artifact docs/figures/formal_v7_update_throughput.svg \
  --artifact docs/figures/rq3_latency_breakdown.svg \
  --artifact docs/figures/rq3_work_correlations.svg \
  --artifact docs/figures/rq3_e2e_cost_model.svg \
  --artifact docs/figures/formal_v7_workload_energy.svg \
  --artifact docs/paper/data/workload_energy/workload_energy.json

printf 'PASS formal-v7 report: %s\n' \
  "${root}/docs/paper/formal_v7_primary_results.pdf"
