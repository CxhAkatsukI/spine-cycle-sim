#!/usr/bin/env bash
set -eo pipefail

root=$(cd -- "$(dirname -- "$0")" && pwd)
primary=$root/l10
out=$root/l10-fast
mkdir -p "$out"/{xclbin,logs,reports,temp}
exec > >(tee -a "$out/build.log") 2>&1
source /data/feiyang/xilinx/settings64-2024.1.sh
cd "$primary/source/tests/test_integration"

platform=xilinx_u55c_gen3x16_xdma_3_202210_1
tag=engine-1-1-1-1-1
reader=$primary/xclbin/spine_partconv_rdmaint_kernel.$tag.mixed.hw.xo
compute=$primary/xclbin/spine_partconv_compute_kernel.$tag.hw.xo
lifecycle=$primary/xclbin/spine_vertex_lifecycle_kernel.$tag.hw.xo
args=(TARGET=hw KERNEL_FREQ=150 ORDERED_MIXED=1 PAPER_ALIGNMENT=1
      ENGINE_COMPUTE=saturating-plus ENGINE_SCHEDULE=changed-frontier
      ENGINE_UPDATE=dependency ENGINE_STORAGE=mirrored-reduced
      ENGINE_NUMERICS=integer-word
      "DEVICE=/data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/$platform/$platform.xpfm"
      "XCLBIN_DIR=$out/xclbin" "VPP_REPORT_DIR=$out/reports" "VPP_LOG_DIR=$out/logs"
      "VPP_TEMP_DIR=$out/temp" VIVADO_SYNTH_JOBS=10 VIVADO_IMPL_JOBS=2
      "PARTITIONED_READMAINT_XO=$reader" "PARTITIONED_COMPUTE_XO=$compute"
      "VERTEX_LIFECYCLE_XO=$lifecycle" -o "$reader" -o "$compute" -o "$lifecycle")
identity=$(make -s "${args[@]}" weighted_build_identity)
test "$identity" = 1f8f7dfd23f5657464644e75d9d1c58f124f08e50b4a059d014d8e0eb0bdc32c
sha256sum "$reader" "$compute" "$lifecycle"
if [[ ${1:-} != --dry-run ]]; then
    # Both active cgroup caps total 280 GiB; keep at least 50 GiB beyond that.
    (( $(awk '$1 == "MemAvailable:" {print $2}' /proc/meminfo) >= 330 * 1024 * 1024 ))
    date -u
    make -j1 "${args[@]}" partitioned_split_e2e_xclbin
    date -u
else
    make -n "${args[@]}" partitioned_split_e2e_xclbin
fi
