#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plot_python="${SPINE_PLOT_PYTHON:-/data/tmp/chuxiao/spine-paper-plot-venv/bin/python}"
source_date_epoch="${SOURCE_DATE_EPOCH:-1785369600}"

if [[ ! -x "${plot_python}" ]]; then
  printf 'plot Python is not executable: %s\n' "${plot_python}" >&2
  exit 2
fi

cd "${root}"
bash scripts/analyze_formal_v6_primary.sh
bash scripts/analyze_formal_v6_update_sweep.sh
"${plot_python}" scripts/render_formal_v6_primary.py
SOURCE_DATE_EPOCH="${source_date_epoch}" FORCE_SOURCE_DATE=1 \
  latexmk -pdf -interaction=nonstopmode -halt-on-error -cd \
    docs/paper/formal_v6_primary_results.tex
SOURCE_DATE_EPOCH="${source_date_epoch}" FORCE_SOURCE_DATE=1 \
  latexmk -c -cd docs/paper/formal_v6_primary_results.tex
python3 scripts/audit_formal_v6_evidence_package.py

printf 'PASS formal-v6 report: %s\n' \
  "${root}/docs/paper/formal_v6_primary_results.pdf"
