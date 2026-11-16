#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
cd "$root/source/tests/test_integration"

vitis=/data/yxx/tools/xilinx/Vitis/2024.1
hls=/data/yxx/tools/xilinx/Vitis_HLS/2024.1
xrt=/opt/xilinx/xrt
identity=$(make -s TARGET=hw KERNEL_FREQ=150 ORDERED_MIXED=1 PAPER_ALIGNMENT=1 \
    ENGINE_COMPUTE=saturating-plus ENGINE_SCHEDULE=changed-frontier ENGINE_UPDATE=dependency \
    ENGINE_STORAGE=mirrored-reduced ENGINE_NUMERICS=integer-word weighted_build_identity)
[[ $identity =~ ^[a-f0-9]{64}$ ]]
g++ -std=c++17 -O2 -Wall -Wno-unknown-pragmas -I. -Istubs -I../../src \
    -I"$vitis/include" -I"$hls/include" -I"$xrt/include" \
    -DMAX_N=16777216 -DVS_PARTITION_SIZE=1048576 -DMAX_SORT_N=131072 -DEDGE_BUF_CHUNK_SIZE=33554432 \
    -DSPINE_ALGORITHM_KIND=0 -DSPINE_ENABLE_SSSP_REPAIR=1 -DSPINE_ENABLE_CC_REPAIR=0 -DSPINE_ENABLE_ORDERED_MIXED=1 \
    -DSPINE_ENABLE_STATIC_ENGINE=1 -DSPINE_COMPUTE_ID=1 -DSPINE_SCHEDULE_ID=1 \
    -DSPINE_UPDATE_ID=1 -DSPINE_STORAGE_ID=1 -DSPINE_NUMERICAL_ID=1 \
    -DSPINE_ENFORCE_PAPER_ALIGNMENT_CONTRACT=1 -DCL_DEVICE_HALF_FP_CONFIG=0x1033 \
    "-DSPINE_WEIGHTED_BUILD_SHA256=\"$identity\"" \
    "$root/fig10b_host.cpp" xcl2.cpp -o "$root/fig10b_host" \
    -L"$xrt/lib" -lOpenCL -lxrt_coreutil -lrt -pthread -lcrypto
