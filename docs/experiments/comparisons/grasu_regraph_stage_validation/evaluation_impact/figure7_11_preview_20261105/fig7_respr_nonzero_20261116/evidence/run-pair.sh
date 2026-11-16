#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
archive=/data/chuxiao/checks/source-retention-repair-20261104
graph=/data/tmp/chuxiao/fullgraph_fpga_workloads_20260806/au_residual_pagerank_insert_u8.graph
spine_image="$archive/respr-host-correction-matrix-v1/au/spine-clock-copy/control.xclbin"
gr_image="$archive/respr-degree-prefix-dual-clock-v2/current-clock-copy/control.xclbin"

export FIG7_RESPR_EPSILON=1e-7
export XILINX_XRT=/opt/xilinx/xrt XCL_DEVICE_INDEX=0
export SPINE_EXPECT_BDF=0000:82:00.1 GRASU_REGRAPH_EXPECT_BDF=0000:82:00.1
export LD_LIBRARY_PATH=/opt/xilinx/xrt/lib:/usr/lib/x86_64-linux-gnu
unset XCL_EMULATION_MODE FIG7_RESPR_PREFLIGHT
sha256sum "$graph" "$spine_image" "$gr_image" rank.f32 ./spine-host \
    ./gr-host-build/sharded_k4_residual_pagerank_native_host > run-inputs.sha256

exec 8</run/lock/card0.lock
flock -w 120 8
if fuser /dev/dri/renderD131; then exit 75; fi
SPINE_RESIDENT_RESERVE_GIB=32 bash \
    /data/chuxiao/spine-respr-fig7-host-refresh-20261115/check-memory.sh 8 | tee board.memory

run() {
    local name=$1
    shift
    printf '%q ' "$@" > "$name.command"
    date -Is > "$name.start"
    set +e
    timeout --kill-after=10s 5m taskset -c 124,125 "$@" > "$name.board.log" 2>&1
    local code=$?
    set -e
    printf '%s\n' "$code" > "$name.exit"
    date -Is > "$name.end"
}
run spine ./spine-host "$spine_image" --dynamic-graph "$graph" --source 0 --resident-benchmark
run gr env FIG7_RESPR_CHECKPOINT="$PWD/rank.f32" GRASU_UPDATE_REPEATS=1 \
    GRASU_SHARDED_PREMIGRATE_INPUTS=1 GRASU_SHARDED_METADATA_REPLICAS=4 \
    GRASU_SHARDED_EVENT_TRACE=0 ./gr-host-build/sharded_k4_residual_pagerank_native_host \
    "$gr_image" "$graph" gr-ranks.txt
cat spine.exit gr.exit
test "$(cat spine.exit)" = 0 && test "$(cat gr.exit)" = 0
