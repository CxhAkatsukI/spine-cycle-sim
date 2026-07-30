#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plot_python="${SPINE_PLOT_PYTHON:-/data/tmp/chuxiao/spine-paper-plot-venv/bin/python}"
source_date_epoch="${SOURCE_DATE_EPOCH:-1785369600}"
data="${root}/docs/paper/data/formal_v7_primary"

if [[ ! -x "${plot_python}" ]]; then
  printf 'plot Python is not executable: %s\n' "${plot_python}" >&2
  exit 2
fi

cd "${root}"
bash scripts/analyze_formal_v7_primary.sh
bash scripts/analyze_formal_v6_update_sweep.sh
"${plot_python}" scripts/render_formal_v6_primary.py \
  --analysis-dir \
    /data/tmp/chuxiao/large_graph_campaign_v1/formal_v7_primary_analysis \
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
  --out "${data}/evidence_package_audit.json" \
  --artifact docs/paper/formal_v7_primary_results.pdf \
  --artifact docs/evidence/formal_v6_r19_k4_preflight_20260730.json \
  --artifact docs/evidence/formal_v6_large_sssp_runtime_projection_20260730.json \
  --artifact docs/paper/data/formal_v7_primary/wall_time_feasibility.json \
  --artifact docs/figures/formal_v7_primary_ratios.svg \
  --artifact docs/figures/formal_v7_memory_locality.svg \
  --artifact docs/figures/formal_v7_update_throughput.svg \
  --artifact docs/figures/rq3_latency_breakdown.svg \
  --artifact docs/figures/rq3_work_correlations.svg

printf 'PASS formal-v7 report: %s\n' \
  "${root}/docs/paper/formal_v7_primary_results.pdf"
