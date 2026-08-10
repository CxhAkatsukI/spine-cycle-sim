#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SNAPSHOT_ROOT=${REFACTOR31_SNAPSHOT_ROOT:-/data/feiyang/spine-dynamic-graph-builds/segmented_exact_fallback_cc7e3f9_20260802/direct_hw_refactor31/host}
XRT_ROOT=${XILINX_XRT:-/opt/xilinx/xrt}
OUTPUT=${1:-/data/feiyang/codex_builds/spine_paper_alignment/refactor31_real_slice_host}

for required in host_split.hpp segmented_exact_replay_reference.hpp xcl2.cpp xcl2.hpp; do
    test -f "${SNAPSHOT_ROOT}/${required}" || {
        printf 'missing frozen refactor31 host input: %s\n' "${SNAPSHOT_ROOT}/${required}" >&2
        exit 1
    }
done

mkdir -p "$(dirname "${OUTPUT}")"
g++ -std=c++17 -O2 -Wall -Wextra -pthread \
    -I"${SNAPSHOT_ROOT}" -I"${XRT_ROOT}/include" \
    "${ROOT}/tools/refactor31/refactor31_real_slice_host.cpp" \
    "${SNAPSHOT_ROOT}/xcl2.cpp" \
    -L"${XRT_ROOT}/lib" -Wl,-rpath,"${XRT_ROOT}/lib" -lOpenCL \
    -o "${OUTPUT}"

sha256sum "${OUTPUT}"
