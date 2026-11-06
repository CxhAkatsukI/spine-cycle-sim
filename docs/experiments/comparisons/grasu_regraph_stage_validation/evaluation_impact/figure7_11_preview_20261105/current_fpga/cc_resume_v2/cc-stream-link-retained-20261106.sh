#!/bin/bash
set -euo pipefail
root=/data/chuxiao/spine-cc-stream-admit-2315cae-route-v3
source /data/feiyang/xilinx/settings64-2024.1.sh
export XILINX_XRT=/data/feiyang/runtime/frontier-xrt-20261015/xilinx/xrt
libs=/data/chuxiao/cc-stream-package-runtime-20261106/lib
export LD_LIBRARY_PATH="$libs:$XILINX_XRT/lib:${LD_LIBRARY_PATH:-}"
export TMPDIR="$root/tmp" XILINX_VITIS_DATA_DIR="$root/user-data"
platform=/data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm
cd "$root/source/tests/test_integration"
image="$root/xclbin/spine_partitioned_split_e2e.engine-4-1-2-2-1.hw.xclbin"
temp="$root/temp/partitioned_split_e2e_link_engine-4-1-2-2-1"
cache="$PWD/.ipcache"
test ! -e "$image"
test ! -e "$root/link-command.txt"
test -r "$platform"
test -r "$libs/libboost_filesystem.so.1.74.0"
test -r "$libs/libboost_program_options.so.1.74.0"
test -d "$cache"
sha256sum --check "$root/inherited-artifacts.sha256"
"$XILINX_XRT/bin/xclbinutil" --version
args=(host_static_engine partitioned_split_e2e_xclbin
    TARGET=hw ALGORITHM=connected_components PAPER_ALIGNMENT=1 KERNEL_FREQ=150
    ENGINE_COMPUTE=minimum-label ENGINE_SCHEDULE=changed-frontier
    ENGINE_UPDATE=closed-region ENGINE_STORAGE=reciprocal-original
    ENGINE_NUMERICS=integer-word DEVICE="$platform" XCLBIN_DIR="$root/xclbin"
    VPP_TEMP_DIR="$root/temp" VPP_REPORT_DIR="$root/reports"
    VPP_LOG_DIR="$root/logs" CC_HOST_OUTPUT="$root/host_cc_repair"
    VPP_LINK_BASE_FLAGS="-t hw --platform $platform --kernel_frequency 150 -O3 --save-temps"
    VPP_REMOTE_IP_CACHE="$cache" VIVADO_SYNTH_JOBS=1 VIVADO_IMPL_JOBS=1)

# Check the generated link command, not the compile-only VPP_FLAGS variable.
make -n -j1 "${args[@]}" > "$root/link-command.txt"
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.link_retention \
    --plan "$root/link-command.txt" --image "$image" --temp "$temp" --cache "$cache" \
    > "$root/link-command-validation.json"
make -j1 "${args[@]}"

impl="$temp/link/vivado/vpl/prj/prj.runs/impl_1"
test -s "$impl/bus_skew_routed.rpt"
test -s "$impl/level0_wrapper_postroute_physopt.dcp"
cp -p "$impl/bus_skew_routed.rpt" "$root/reports/bus_skew_routed.rpt"
cp -p "$impl/level0_wrapper_postroute_physopt.dcp" "$root/reports/"
