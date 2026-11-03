# Spine Artifact Inventory

Only readable files under `/data/feiyang` were searched; inaccessible
directories are not evidence of absent artifacts. File date and filename
are not hardware correctness or performance admission.

## Images Used By The October 26 Matrix

| Algorithm | Image absolute path | SHA-256 |
| --- | --- | --- |
| SSSP | `/data/feiyang/spine-hls-repair-builds/baseline-20261008-clean345f3df-v1/hw/xclbin/spine_partitioned_split_e2e.hw.xclbin` | `2000ded183adffce4880792a3edcefa82eb462c460777fd536602397a77cf5dd` |
| CC | `/data/feiyang/codex_builds/spine_paper_alignment/owner_fifo_hw_v1/cc/xclbin/spine_partitioned_split_e2e.cc.hw.xclbin` | `e3d103fcca2c6718ffaacdc6309db9b39047714c53e15c77a087149997f0096b` |
| ResPR | `/data/chuxiao/builds/grasu-cache-extent-20261025/spine-respr-zfs-v1/build/respr/xclbin/spine_partitioned_split_e2e.respr.hw.xclbin` | `b6cb210342029a77233740e7aeffea354d19757ebb68431b0fc993bef59bd15b` |

The corresponding host/source/configuration pins are in each
`/data/chuxiao/checks/grasu-replicated-host-singlepass-20261026-v1/matrix/{sssp,cc,respr}-au/manifest.json`.
These are actual hardware images, not the newer generalized emulation files.

## Later CC Repair Candidate

- Image: `/data/feiyang/spine-hls-cc-builds/cc-seele-import-20261016-v2/remote-build/output/spine_partitioned_split_e2e.cc_repair.hw.xclbin`.
- Image SHA-256: `4071c0f792530fb0b62e6fc4a404ce1c78087c866d2c7c6f44c9fc2d05e64c62`.
- Source identity: `1e26bd9bf5c9b9bdd5a92e0248bc8e60bbf0d736597311082bd068b096b0c72a`.
- Existing runtime: `/data/feiyang/spine-hls-cc-builds/cc-seele-runtime-20261016-v1/hw/run-canonical-v1/`.

The existing run exits zero and reports `CC_REPAIR_PASS vertices=12
updates=44 all_raw_labels_checked=1 all_raw_graphs_checked=1
all_round_work_checked=1`. Its supervisor nevertheless records
`accepted=false`, `ValueError: malformed clock evidence`. The saved clock
log is four plain numbers (`150`, `500`, `450`, `0`), so this is not itself
a graph-correctness mismatch. Neither is it an accepted eight-graph timing
run. ABI, actual clock interpretation, workload support and host compatibility
must be checked before substituting this image in a comparison.

The more recent readable generalized build trees contained `sw_emu` and
`hw_emu` images, not a later admitted routed three-algorithm set. They must
not silently replace FPGA measurements.

## Current Candidate Check

The native host is
`/data/feiyang/spine-hls-cc-builds/cc-seele-native-host-20261016-v1/hw/host_cc_repair`,
SHA-256 `b00bd66e500838b0f49e4acc180c28ac88cffdfa938aae041b86b73c9ba0082b`.
Its default fixture has twelve vertices but still allocates sixteen fixed
graph buffers of 524,881,920 bytes each, about 7.82 GiB before other buffers.
An 8-GiB/7-GiB-high cgroup is therefore insufficient. The first owned attempt
was stopped during allocation, before reporting a successful test; its raw
output remains under
`/data/chuxiao/checks/source-retention-repair-20261104/spine-cc-candidate-once-v1/`.

The separately owned `source_retention.spine_smoke` runner uses the existing
24-GiB/22-GiB-high, zero-swap board policy and full finite peer-budget
admission, plus a 32-GiB live reserve and four-minute execution watchdog.
It requests device 0 only after memory admission and an idle-board check.
It verifies eleven distinct partial-repair batches in one sample, raw graph,
label and round-work gates, and the resident image UUID/actual driver clocks.
None of these checks is a performance admission or an eight-graph comparison.

The second attempt in `spine-cc-candidate-once-v2/` was rejected **before
requesting the board** because competing compiler cgroups did not have the
required finite, zero-swap peer-budget evidence. Its own peak was 17,731,584
bytes, with no throttling or OOM event. Available memory at that check was
108,814,893,056 bytes; the rejection is not a claim that physical available
memory was only a few GiB. The R route continues independently. The candidate
therefore remains unqualified by this new runner, not a failed CC result.
