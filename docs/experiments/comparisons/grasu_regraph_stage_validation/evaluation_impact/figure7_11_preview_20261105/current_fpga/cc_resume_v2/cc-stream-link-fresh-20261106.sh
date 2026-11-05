#!/bin/bash
set -euo pipefail
root=/data/chuxiao/spine-cc-stream-admit-2315cae-route-v2
source /data/feiyang/xilinx/settings64-2024.1.sh
export XILINX_XRT=/data/feiyang/runtime/frontier-xrt-20261015/xilinx/xrt
libs=/data/chuxiao/cc-stream-package-runtime-20261106/lib
export LD_LIBRARY_PATH="$libs:$XILINX_XRT/lib:${LD_LIBRARY_PATH:-}"
export TMPDIR="$root/tmp" XILINX_VITIS_DATA_DIR="$root/user-data"
platform=/data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm
cd "$root/source/tests/test_integration"
test -r "$platform"
test -r "$libs/libboost_filesystem.so.1.74.0"
test -r "$libs/libboost_program_options.so.1.74.0"
sha256sum --check "$root/inherited-artifacts.sha256"
"$XILINX_XRT/bin/xclbinutil" --version
make -j1 host_static_engine partitioned_split_e2e_xclbin \
    TARGET=hw ALGORITHM=connected_components PAPER_ALIGNMENT=1 KERNEL_FREQ=150 \
    ENGINE_COMPUTE=minimum-label ENGINE_SCHEDULE=changed-frontier \
    ENGINE_UPDATE=closed-region ENGINE_STORAGE=reciprocal-original \
    ENGINE_NUMERICS=integer-word DEVICE="$platform" XCLBIN_DIR="$root/xclbin" \
    VPP_TEMP_DIR="$root/temp" VPP_REPORT_DIR="$root/reports" \
    VPP_LOG_DIR="$root/logs" CC_HOST_OUTPUT="$root/host_cc_repair" \
    VIVADO_SYNTH_JOBS=1 VIVADO_IMPL_JOBS=1

# Retain the routed design and skew report outside Vitis's disposable project.
impl="$root/temp/partitioned_split_e2e_link_engine-4-1-2-2-1/link/vivado/vpl/prj/prj.runs/impl_1"
cp -p "$impl/bus_skew_routed.rpt" "$root/reports/bus_skew_routed.rpt"
cp -p "$impl/level0_wrapper_postroute_physopt.dcp" "$root/reports/"
