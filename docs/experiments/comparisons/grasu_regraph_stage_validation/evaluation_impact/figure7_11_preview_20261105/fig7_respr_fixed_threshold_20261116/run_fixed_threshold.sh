#!/usr/bin/env bash
set -euo pipefail
script=$(realpath "$0")
previous=$(realpath "${1:?previous run root}")
scratch=$(realpath "${2:?scratch directory}")
shift 2
inputs=/data/chuxiao/spine-respr-fig7-host-refresh-20261115
gr_image=/data/chuxiao/checks/source-retention-repair-20261104/respr-degree-prefix-dual-clock-v2/current-clock-copy/control.xclbin
bdf=0000:82:00.1
render=/dev/dri/renderD131

if [[ ${1:-} != --case ]]; then
    for spec in "$@"; do
        IFS=: read -r group dataset cap <<< "$spec"
        dir="$scratch/$group/$dataset"
        mkdir -p "$scratch/$group"
        mkdir "$dir" || continue
        printf '%s begin %s %s (cap %s GiB)\n' "$(date -Is)" "$group" "$dataset" "$cap"
        code=0
        systemd-run --user --unit="fig7-fixed-${group}-${dataset,,}-$$" --quiet --wait --pipe \
            -p "MemoryMax=${cap}G" -p MemorySwapMax=0 \
            bash "$script" "$previous" "$scratch" --case "$group" "$dataset" "$cap" \
            2>&1 | tee "$dir/case.log" || code=$?
        printf '%s\n' "$code" > "$dir/case.exit"
        printf '%s end %s %s (exit %s)\n' "$(date -Is)" "$group" "$dataset" "$code"
    done
    exit
fi

group=$2 dataset=$3 cap=$4
cd "$scratch/$group/$dataset"
case "$group" in
    high) export FIG7_RESPR_EPSILON=1e-7 ;;
    low) export FIG7_RESPR_EPSILON=3e-9 ;;
    *) exit 64 ;;
esac
checkpoint="$previous/respr-matrix/$dataset/rank.f32"
[[ $dataset != AU ]] || checkpoint="$previous/rank.f32"
gr_build=gr-host-build
case "$dataset" in PK|LJ|LJ08) gr_build=gr-shared-rank-build ;; esac
gr_host="$previous/$gr_build/sharded_k4_residual_pagerank_native_host"
mapfile -t row < "$inputs/$dataset.inputs"
spine_image=${row[2]} graph=${row[3]} source=${row[4]} cpu=${row[5]}
export XILINX_XRT=/opt/xilinx/xrt XCL_DEVICE_INDEX=0
export SPINE_EXPECT_BDF="$bdf" GRASU_REGRAPH_EXPECT_BDF="$bdf"
export LD_LIBRARY_PATH=/opt/xilinx/xrt/lib:/usr/lib/x86_64-linux-gnu
unset XCL_EMULATION_MODE FIG7_RESPR_PREFLIGHT

memory() {
    SPINE_RESIDENT_RESERVE_GIB=32 bash "$inputs/check-memory.sh" "$cap"
}
run() {
    local name=$1 code=0
    shift
    {
        printf 'FIG7_RESPR_EPSILON=%q timeout --kill-after=10s 18m taskset -c %q' "$FIG7_RESPR_EPSILON" "$cpu"
        printf ' %q' "$@"
        printf '\n'
    } > "$name.command"
    date -Is > "$name.start"
    timeout --kill-after=10s 18m taskset -c "$cpu" "$@" > "$name.log" 2>&1 || code=$?
    printf '%s\n' "$code" > "$name.exit"
    date -Is > "$name.end"
    return "$code"
}

test -s "$checkpoint"
printf 'threshold=%s checkpoint=%s graph=%s board=%s\n' "$FIG7_RESPR_EPSILON" "$checkpoint" "$graph" "$bdf"
memory | tee preflight.memory
exec 8< /run/lock/card0.lock
flock -w 180 8
if ! awk '$1 == "contexts:" { found=1; available=($2 == 0) } END { exit !(found && available) }' \
    "/sys/bus/pci/devices/$bdf/kdsstat" || fuser "$render"; then
    echo "Board $bdf has existing contexts" >&2
    exit 75
fi
memory | tee board.memory
spine_code=0 gr_code=0
run spine "$previous/spine-host" "$spine_image" --dynamic-graph "$graph" --source "$source" \
    --resident-benchmark || spine_code=$?
rg '^RESIDENT_PROPAGATION |^SPINE_RESIDENT_BENCHMARK_PASS ' spine.log || tail -n 10 spine.log
if (( spine_code != 0 )); then exit "$spine_code"; fi
memory | tee gr.memory
run gr env FIG7_RESPR_CHECKPOINT="$checkpoint" GRASU_UPDATE_REPEATS=1 \
    GRASU_SHARDED_PREMIGRATE_INPUTS=1 GRASU_SHARDED_METADATA_REPLICAS=4 \
    GRASU_SHARDED_EVENT_TRACE=0 "$gr_host" "$gr_image" "$graph" gr-ranks.txt || gr_code=$?
rg '^SHARED_RESPR_CHECKPOINT |^RESIDUAL_PR_PMA_NATIVE_SHARDED_(INPUT|TIMING|RESULT) ' gr.log || tail -n 10 gr.log
flock -u 8
if (( gr_code != 0 )); then exit "$gr_code"; fi
cg=$(awk -F: '$1 == "0" {print $3}' /proc/self/cgroup)
if [[ -r /sys/fs/cgroup"$cg"/memory.peak ]]; then
    cp /sys/fs/cgroup"$cg"/memory.peak memory.peak
fi
