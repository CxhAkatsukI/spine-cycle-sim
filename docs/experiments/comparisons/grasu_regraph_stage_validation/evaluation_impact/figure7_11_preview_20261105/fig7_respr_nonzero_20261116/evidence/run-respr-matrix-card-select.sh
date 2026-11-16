#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")" && pwd)
inputs=/data/chuxiao/spine-respr-fig7-host-refresh-20261115
gr_image=/data/chuxiao/checks/source-retention-repair-20261104/respr-degree-prefix-dual-clock-v2/current-clock-copy/control.xclbin
run_dir=${RUN_DIR:-"$root/respr-matrix"}
reserve=${SPINE_RESIDENT_RESERVE_GIB:-32}
resume_from=${RESUME_MATRIX:-}
card=${FIG7_CARD:-0}
case "$card" in
    0) bdf=0000:82:00.1; render=/dev/dri/renderD131 ;;
    1) bdf=0000:c1:00.1; render=/dev/dri/renderD129 ;;
    *) echo "Invalid FIG7_CARD: $card" >&2; exit 64 ;;
esac

if [[ ${1:-} != --case ]]; then
    mkdir -p "$run_dir"
    for spec in "$@"; do
        dataset=${spec%:*}
        cap=${spec#*:}
        dir="$run_dir/$dataset"
        if ! mkdir "$dir"; then continue; fi
        printf '%s begin %s (cap %s GiB)\n' "$(date -Is)" "$dataset" "$cap"
        code=0
        unit="fig7-respr-${dataset,,}-$$"
        printf '%s.service\n' "$unit" > "$dir/systemd.unit"
        systemd-run --user --unit="$unit" --quiet --wait --pipe -p "MemoryMax=${cap}G" -p MemorySwapMax=0 \
            env FIG7_CARD="$card" bash "$0" --case "$dataset" "$cap" "$dir" "$reserve" "$resume_from" \
            2>&1 | tee "$dir/case.log" || code=$?
        printf '%s\n' "$code" > "$dir/case.exit"
        printf '%s end %s (exit %s)\n' "$(date -Is)" "$dataset" "$code"
    done
    exit
fi

dataset=$2 cap=$3 dir=$4 reserve=$5 resume_from=${6:-}
cd "$dir"
mapfile -t row < "$inputs/$dataset.inputs"
spine_image=${row[2]} graph=${row[3]} source=${row[4]} cpu=${row[5]}
export XILINX_XRT=/opt/xilinx/xrt XCL_DEVICE_INDEX="$card"
export SPINE_EXPECT_BDF="$bdf" GRASU_REGRAPH_EXPECT_BDF="$bdf"
export LD_LIBRARY_PATH=/opt/xilinx/xrt/lib:/usr/lib/x86_64-linux-gnu
unset XCL_EMULATION_MODE FIG7_RESPR_PREFLIGHT

memory() {
    SPINE_RESIDENT_RESERVE_GIB="$reserve" bash "$inputs/check-memory.sh" "$cap"
}
run() {
    local name=$1 code=0
    shift
    printf 'FIG7_RESPR_EPSILON=%q ' "$FIG7_RESPR_EPSILON" > "$name.command"
    printf '%q ' "$@" >> "$name.command"
    printf '\n' >> "$name.command"
    date -Is > "$name.start"
    timeout --kill-after=10s 18m taskset -c "$cpu" "$@" > "$name.log" 2>&1 || code=$?
    printf '%s\n' "$code" > "$name.exit"
    date -Is > "$name.end"
    return "$code"
}

memory | tee preflight.memory
spine=("$root/spine-host" "$spine_image" --dynamic-graph "$graph" --source "$source" --resident-benchmark)
export FIG7_RESPR_EPSILON=1e-7
reused_spine=0
if [[ -n $resume_from && -r $resume_from/$dataset/preflight.exit && $(< "$resume_from/$dataset/preflight.exit") == 0 ]]; then
    previous="$resume_from/$dataset"
    cp -l "$previous/rank.f32" rank.f32
    cp "$previous"/preflight.{log,command,start,end,exit} .
    printf 'Reusing CPU preflight checkpoint from %s\n' "$previous"
    if [[ -r $previous/spine.exit && $(< "$previous/spine.exit") == 0 ]] &&
        rg -q "^SPINE_DEVICE bdf=${bdf//./\\.}($| )" "$previous/spine.log"; then
        cp "$previous"/spine.{log,command,start,end,exit} .
        printf 'Reusing passed Delta.hls measurement on %s\n' "$bdf"
        reused_spine=1
    fi
else
    printf 'CPU preflight %s\n' "$dataset"
    run preflight env FIG7_RESPR_PREFLIGHT="$PWD/rank.f32" "${spine[@]}"
fi
rg '^RESIDENT_PREFLIGHT ' preflight.log

# Prefer the AU threshold; change it only if the old and updated activity disagree.
export FIG7_RESPR_EPSILON
FIG7_RESPR_EPSILON=$(awk '
    /^RESIDENT_PREFLIGHT / {
        for (i=2; i<=NF; i++) { split($i,a,"="); val[a[1]]=a[2] }
    }
    END {
        if (val["old_active"] == "0" && val["updated_active"]+0 > 0) { print "1e-7"; exit }
        n=split("1e-6 3e-7 1e-7 3e-8 1e-8 3e-9 1e-9", choices, " ")
        for(i=1; i<=n; i++)
            if (choices[i]+0 > val["old_max_residual"]+0 && choices[i]+0 < val["updated_max_residual"]+0) {
                print choices[i]; exit
            }
        exit 1
    }
' preflight.log) || { echo 'No clean nonzero threshold in the ladder for the original batch'; exit 65; }
printf '%s\n' "$FIG7_RESPR_EPSILON" > epsilon.txt
printf 'Board threshold %s for %s; acquiring lock on %s\n' "$FIG7_RESPR_EPSILON" "$dataset" "$bdf"
exec 8<"/run/lock/card${card}.lock"
flock -w 180 8
if ! awk '$1 == "contexts:" { found=1; available=($2 == 0) } END { exit !(found && available) }' \
    "/sys/bus/pci/devices/$bdf/kdsstat" || fuser "$render"; then
    echo "Board $bdf has existing contexts" >&2
    exit 75
fi
memory | tee board.memory

spine_code=0 gr_code=0
if (( ! reused_spine )); then
    run spine "${spine[@]}" || spine_code=$?
fi
rg '^RESIDENT_PROPAGATION |^SPINE_RESIDENT_BENCHMARK_PASS ' spine.log || tail -n 6 spine.log
if (( spine_code != 0 )); then exit "$spine_code"; fi
memory | tee gr.memory
run gr env FIG7_RESPR_CHECKPOINT="$PWD/rank.f32" GRASU_UPDATE_REPEATS=1 \
    GRASU_SHARDED_PREMIGRATE_INPUTS=1 GRASU_SHARDED_METADATA_REPLICAS=4 \
    GRASU_SHARDED_EVENT_TRACE=0 "$root/gr-host-build/sharded_k4_residual_pagerank_native_host" \
    "$gr_image" "$graph" gr-ranks.txt || gr_code=$?
rg '^SHARED_RESPR_CHECKPOINT |^RESIDUAL_PR_PMA_NATIVE_SHARDED_(INPUT|TIMING|RESULT) ' gr.log || tail -n 10 gr.log
flock -u 8
if (( gr_code != 0 )); then exit "$gr_code"; fi
cg=$(awk -F: '$1 == "0" {print $3}' /proc/self/cgroup)
if [[ -r /sys/fs/cgroup"$cg"/memory.peak ]]; then
    cp /sys/fs/cgroup"$cg"/memory.peak memory.peak
fi
sha256sum "$graph" "$spine_image" "$gr_image" rank.f32 "$root/spine-host" \
    "$root/gr-host-build/sharded_k4_residual_pagerank_native_host" > run-inputs.sha256
