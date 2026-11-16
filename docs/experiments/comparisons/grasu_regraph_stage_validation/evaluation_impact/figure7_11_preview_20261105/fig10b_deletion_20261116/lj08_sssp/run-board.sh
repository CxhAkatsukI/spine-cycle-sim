#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
exec > >(tee -a "$root/board.log") 2>&1

remote=chuxiao@10.129.165.42
image_name=spine_partitioned_split_e2e.engine-1-1-1-1-1.mixed.hw.xclbin
image=$root/image/$image_name
result=$root/fig10b_lj08_delta.csv
frozen=/data/chuxiao/fig7-respr-propagation-fig10b-20261116.cnPau7QX/fig10b-lj08-sssp-frozen
lock=/data/feiyang/spine-dynamic-graph-builds/paper-a-xrt-20260917/physical-u55c-82.lock
card=/sys/bus/pci/devices/0000:82:00.1
memcheck=/data/chuxiao/spine-respr-fig7-host-refresh-20261115/check-memory.sh
ssh_args=(-o BatchMode=yes -o ConnectTimeout=10 -p 23333)
export XILINX_XRT=/opt/xilinx/xrt
export LD_LIBRARY_PATH=/opt/xilinx/xrt/lib:/usr/lib/x86_64-linux-gnu
unset XCL_EMULATION_MODE

for pct in 050 100 025 075 000; do
    test -e "$root/cases/delete$pct/ready"
done
if [[ -s $image.source ]]; then
    remote_image=$(< "$image.source")
else
    [[ ! -e $result || $(wc -l < "$result") -le 1 ]]
    printf '%s Waiting for either LJ08 build on Seele.\n' "$(date -u +%FT%TZ)"
    remote_image=
fi
while [[ -z $remote_image ]]; do
    failed_builds=0
    for variant in l10-fast l10; do
        candidate=$root/$variant/xclbin/$image_name
        if status=$(ssh "${ssh_args[@]}" "$remote" \
            "systemctl --user show fig10b-lj08-$variant -p ActiveState -p Result; test ! -s '$candidate.weighted-manifest' || printf 'MANIFEST_READY\\n'"); then
            if [[ $status == *ActiveState=inactive* && $status == *Result=success* && $status == *MANIFEST_READY* ]]; then
                remote_image=$candidate
                break 2
            fi
            if [[ $status == *ActiveState=failed* ]]; then
                failed_builds=$((failed_builds + 1))
            fi
        fi
    done
    if (( failed_builds == 2 )); then
        printf '%s Both Seele builds failed; see their respective build.log.\n' "$(date -u +%FT%TZ)"
        exit 1
    fi
    sleep 120
done

if [[ ! -s $image.source ]]; then
    mkdir -p "$root/image"
    rsync -a -e 'ssh -o BatchMode=yes -o ConnectTimeout=10 -p 23333' \
        "$remote:$remote_image" "$remote:$remote_image.weighted-manifest" "$root/image/"
fi
expected=$(awk '$1 == "image_sha256" {print $2}' "$image.weighted-manifest")
actual=$(sha256sum "$image")
[[ $expected =~ ^[a-f0-9]{64}$ && ${actual%% *} == "$expected" ]]
printf '%s\n' "$remote_image" > "$image.source.tmp"
mv -- "$image.source.tmp" "$image.source"
printf '%s FPGA image ready sha256=%s source=%s\n' "$(date -u +%FT%TZ)" "$expected" "$remote_image"

if [[ ! -e $result ]]; then
    printf '%s\n' 'deletion_pct,deletions,insertions,wall_ms,publication_ms,affected,resets,rounds,records' > "$result"
fi
failed=0
for pct in 050 100 025 075 000; do
    numeric=$((10#$pct))
    if grep -q "^$numeric," "$result"; then continue; fi
    case_dir=$root/cases/delete$pct
    while true; do
        exec 8<"$lock"
        exec 9</run/lock/card0.lock
        if flock -w 60 8 &&
           flock -w 60 9 &&
           [[ $(< "$card/ready") == 0x1 ]] &&
           ! grep -Eq '^(contexts|outstanding execs):[[:space:]]*[1-9]' "$card/kdsstat" &&
           ! fuser /dev/dri/renderD131 &&
           SPINE_RESIDENT_RESERVE_GIB=32 bash "$memcheck" 24; then
            break
        fi
        exec 8<&-
        exec 9<&-
        printf '%s Waiting for idle U55C and 56 GiB available (including 32 GiB reserve); %s\n' \
            "$(date -u +%FT%TZ)" "$(awk '$1 == "MemAvailable:" {print}' /proc/meminfo)"
        sleep 120
    done
    log=$case_dir/board-$(date -u +%Y%m%dT%H%M%SZ).log
    printf '%s Running %s%% on U55C 0000:82:00.1; %s\n' "$(date -u +%FT%TZ)" "$numeric" "$log"
    if timeout --kill-after=2m 90m "$root/fig10b_host" "$image" "$frozen/base.bin" \
        "$case_dir/batch.slice" "$frozen/oracle.before" "$case_dir/oracle.after" "$numeric" \
        2>&1 | tee "$log"; then
        awk '/^FIG10B_PASS / {for(i=2;i<=NF;i++) {split($i,x,"="); printf "%s%s", x[2], i==NF?"\n":","}; found=1} END {if(!found) exit 1}' \
            "$log" >> "$result"
        if ! bash "$root/stage-point.sh" "$log" "$case_dir/batch.slice" "$image.weighted-manifest"; then
            printf '%s Accepted %s%% saved locally; handoff staging failed.\n' "$(date -u +%FT%TZ)" "$numeric"
        fi
    else
        failed=1
        printf '%s Failed %s%%; no result added.\n' "$(date -u +%FT%TZ)" "$numeric"
    fi
    exec 8<&-
    exec 9<&-
done
exit "$failed"
