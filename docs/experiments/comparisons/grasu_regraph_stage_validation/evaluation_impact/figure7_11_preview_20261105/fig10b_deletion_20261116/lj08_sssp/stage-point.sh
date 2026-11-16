#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
log=$1
batch=$2
manifest=$3
parent=/data/chuxiao/worktrees/spine-fig7-respr-host-handoff-20261115/docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105/fig10b_deletion_20261116
out=$parent/lj08_sssp
inputs=/data/tmp/spine-lj08-sssp-u512-deletion-batches-20261116/manifest.tsv

test -f "$parent/README.md"
grep -q '^FIG10B_PASS ' "$log"
case_name=$(basename -- "$(dirname -- "$batch")")
mkdir -p "$out/raw/$case_name"
cp -- "$log" "$batch" "$out/raw/$case_name/"
cp -- "$inputs" "$out/input_manifest.tsv"
if ! cmp -s -- "$manifest" "$out/image.weighted-manifest" ||
   [[ ! -s "$out/xclbin-info.txt" ]]; then
    if /opt/xilinx/xrt/bin/xclbinutil --input "${manifest%.weighted-manifest}" --info \
        > "$out/.xclbin-info.tmp"; then
        mv -- "$out/.xclbin-info.tmp" "$out/xclbin-info.txt"
    else
        rm -f -- "$out/.xclbin-info.tmp" "$out/xclbin-info.txt"
        printf 'Warning: could not read linked image metadata.\n' >&2
    fi
fi
cp -- "$manifest" "$out/image.weighted-manifest"
cp -- "${manifest%.weighted-manifest}.source" "$out/image.source"
cp -- "$root"/{fig10b_host.cpp,lj08_preload.hpp,lj08_placement.hpp,kernel-host.patch,build-host.sh,build.sh,link-fast.sh,prepare.py,run-board.sh,stage-point.sh,compare.py} "$out/"
cp -- "$root/HANDOFF.md" "$out/README.md"
cp -- "$root/fig10b_lj08_delta.csv" "$out/.results.csv.tmp"
mv -- "$out/.results.csv.tmp" "$out/results.csv"
python3 "$root/compare.py" "$out/results.csv" "$parent/results.csv" "$out/input_manifest.tsv" \
    > "$out/.comparison.csv.tmp"
mv -- "$out/.comparison.csv.tmp" "$out/comparison.csv"
