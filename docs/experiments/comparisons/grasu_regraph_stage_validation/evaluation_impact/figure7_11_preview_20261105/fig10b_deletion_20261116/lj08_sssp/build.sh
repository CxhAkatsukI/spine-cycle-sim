#!/usr/bin/env bash
set -eo pipefail

root=$(cd -- "$(dirname -- "$0")" && pwd)
exec > >(tee -a "$root/build.log") 2>&1
source /data/feiyang/xilinx/settings64-2024.1.sh
cd "$root/source/tests/test_integration"

platform=xilinx_u55c_gen3x16_xdma_3_202210_1
args=(TARGET=hw KERNEL_FREQ=150 ORDERED_MIXED=1 PAPER_ALIGNMENT=1
      ENGINE_COMPUTE=saturating-plus ENGINE_SCHEDULE=changed-frontier
      ENGINE_UPDATE=dependency ENGINE_STORAGE=mirrored-reduced
      ENGINE_NUMERICS=integer-word
      "DEVICE=/data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/$platform/$platform.xpfm"
      "XCLBIN_DIR=$root/xclbin" "VPP_REPORT_DIR=$root/reports" "VPP_LOG_DIR=$root/logs"
      VIVADO_SYNTH_JOBS=2 VIVADO_IMPL_JOBS=2)
mkdir -p "$root"/{xclbin,logs,reports,temp}
date -u
make -s "${args[@]}" weighted_build_identity
make "${args[@]}" "VPP_TEMP_DIR=$root/temp" static_engine_reader_xo

# Wait for the host to have both the cgroup hard cap and 50 GiB of headroom.
while (( $(awk '$1 == "MemAvailable:" {print $2}' /proc/meminfo) < 210 * 1024 * 1024 )); do
    printf '%s Waiting for 210 GiB MemAvailable before starting physical link.\n' "$(date -u +%FT%TZ)"
    sleep 180
done
date -u
make -j1 "${args[@]}" "VPP_TEMP_DIR=$root/temp" partitioned_split_e2e_xclbin
date -u
