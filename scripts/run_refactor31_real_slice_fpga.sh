#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
XRT_ROOT=${XILINX_XRT:-/opt/xilinx/xrt}
HOST=${REFACTOR31_HOST:-/data/feiyang/codex_builds/spine_paper_alignment/refactor31_real_slice_host}
XCLBIN=${REFACTOR31_XCLBIN:-/data/feiyang/spine-dynamic-graph-builds/segmented_exact_fallback_cc7e3f9_20260802/hw_refactor31_ii4_bitmap/xclbin/spine_partitioned_split_e2e.hw.xclbin}
EXPECTED_XCLBIN_SHA256=16ca09f5597d974e6963ac19ada4f59a8e2b0d6b7ef5ea8f668e5ffb520a1629
EXPECTED_HOST_SHA256=97b88b4108fa586b4bf68c81682d03a86623f5777edd4f8d28344b25a75ef0f8

if (( $# < 2 )); then
    printf 'Usage: %s SLICE OUT_DIR [SOURCE] [REPEATS]\n' "$0" >&2
    exit 1
fi
SLICE=$(realpath "$1")
OUT_DIR=$(realpath -m "$2")
SOURCE=${3:-}
REPEATS=${4:-5}
[[ ${REPEATS} =~ ^[1-9][0-9]*$ ]] || { echo 'REPEATS must be positive' >&2; exit 1; }
test -x "${HOST}"
test -f "${SLICE}"
test -f "${XCLBIN}"
actual_host_hash=$(sha256sum "${HOST}" | cut -d' ' -f1)
test "${actual_host_hash}" = "${EXPECTED_HOST_SHA256}" || {
    printf 'host hash mismatch: %s\n' "${actual_host_hash}" >&2
    exit 1
}
actual_hash=$(sha256sum "${XCLBIN}" | cut -d' ' -f1)
test "${actual_hash}" = "${EXPECTED_XCLBIN_SHA256}" || {
    printf 'routed xclbin hash mismatch: %s\n' "${actual_hash}" >&2
    exit 1
}

mkdir -p "${OUT_DIR}"
for repeat in $(seq 1 "${REPEATS}"); do
    command=("${HOST}" "${XCLBIN}" --slice "${SLICE}")
    if [[ -n ${SOURCE} ]]; then command+=(--source "${SOURCE}"); fi
    env -u XCL_EMULATION_MODE \
        XILINX_XRT="${XRT_ROOT}" \
        LD_LIBRARY_PATH="${XRT_ROOT}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
        SPINE_PARTITIONED_SPLIT=1 XCL_DEVICE_INDEX="${XCL_DEVICE_INDEX:-0}" \
        timeout --signal=TERM --kill-after=120s "${REFACTOR31_TIMEOUT_SECONDS:-14400}" \
        "${command[@]}" |& tee "${OUT_DIR}/repeat_${repeat}.log"
done

PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}" python3 - "${OUT_DIR}" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
from spine_cycle_sim.calibration.refactor31 import load_refactor31_real_slice_fpga_logs

records = load_refactor31_real_slice_fpga_logs(sorted(root.glob("repeat_*.log")))
if not records or not all(record.correctness_admitted for record in records):
    raise SystemExit("real-slice FPGA admission failed")
shape = {(r.slice, r.source, r.vertices, r.graph_edges) for r in records}
if len(shape) != 1:
    raise SystemExit("real-slice FPGA repeat shape mismatch")
print(f"REFACTOR31_REAL_SLICE_REPEATS_PASS repeats={len(records)}")
PY
