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

### Later Weighted SSSP Images

`xclbinutil --info` distinguishes two later routed images under
`/data/feiyang/spine-hls-weighted-builds/` from the October matrix image:

| Path under the build root | Exported kernel interface |
| --- | --- |
| `weighted-emulation-20261010-v2/integrated/hw/xclbin/spine_integration.hw.xclbin` | Scatter, sorter, convergence reader/reorder and maintenance kernels |
| `weighted-emulation-20261010-v3/partitioned/hw/xclbin/spine_partmaint.hw.xclbin` | `spine_partmaint_kernel` only |

Neither exports the matrix host's `spine_vertex_lifecycle_kernel`,
`spine_partconv_compute_kernel`, or `spine_partconv_rdmaint_kernel`. They
cannot replace the production SSSP image without a different host and a new
qualification of the resident-update boundary.

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
memory was only a few GiB. The R route continued independently.

The third attempt uses the same 24/22-GiB policy, with bounded admission
waiting instead of repeated manual launches. Service
`spine-cc-candidate-smoke-v3-20261104.service`, invocation
`b266c99b284549d2b89cc92906c8a159`, writes to
`/data/chuxiao/checks/source-retention-repair-20261104/spine-cc-candidate-once-v3/`.
It rechecks unchanged image/host/runner pins and the complete peer budgets
every thirty seconds for at most six hours. Waiting requests neither the
board nor a compiler reservation. Admission triggers exactly one canonical
sample, not a timing matrix; expiration retains the rejection without
weakening the policy.

The third attempt **passed** on U55C device 0 (`0000:82:00.1`). The
[raw evidence archive](spine-cc-candidate-once-v3.tar.gz) includes
`results.json` and `spine_cc.stdout.txt`: eleven distinct 12-vertex update
batches, each with checked graph, final labels, and propagation work. Its
`spine_cc.clock.json` matches the resident UUID
`ea373f8d-0b1a-633b-e27b-aaa7a3690c3a` and records a 150 MHz compute clock.
Cgroup peak was 9,005,404,160 bytes (8.39 GiB); memory events were all zero.

This is a correctness and clock check, not a Fig. 7 replacement. The
candidate uses a different host ABI and its reported convergence timer
excludes the final audit/readback. A paired large-graph test must first
match the workload and observable timing boundary; the fixture timings
cannot be divided by any old G+R measurements.

## Full AU CC Qualification

The original October matrix AU input (`au_connected_components_insert_u8.graph`,
SHA-256 `66eb4ba111ceec80ce9c6496cd04c34aa74cedfc813dc37dd55417d2a03dbc90`)
was split with `source_retention.spine_cc_input` for the later repair host.
This only changes serialization: the 515,281-vertex domain, 679,246 directed
edge records and 16 signed records (eight reciprocal insertions) are unchanged.
The native host passed `--layout-only` on this input in a bounded 2-GiB service
(133.4 MiB peak); both cold and hot layouts fit. This check does not open a card.

The first single cold-layout, partial-repair board sample was queued as
`spine-cc-au-repair-check-20261104.service`, invocation
`fd2c03bb1e2e44819d6b53f327e16e85`. Its evidence is
`/data/chuxiao/checks/source-retention-repair-20261104/spine-cc-au-board-v1/results.json`.
It was withdrawn while waiting for memory, with the board lease held by the
withdrawal command and no board stdout. The saved `WAITING_FOR_MEMORY_ADMISSION`
receipt describes its last check, not a live service. No AU sample was spent.

### One AU Sample With Resident Wall Timing

The [`spine_cc_resident_wall.patch`](../../../../../../../patches/spine_cc_resident_wall.patch)
only changes the native host, not the bitstream. It preserves the prior
update-to-publication measurement and all graph, label and round-work oracles.
It records two additional continuous wall times through the same final label
readback: one starting before host packing, the other immediately after
blocking batch upload. The timer includes launch/wait, control readbacks,
propagation and publication. The offline CPU oracle, raw graph audit and
old-graph bootstrap are outside both timers. The returned labels are also
used for validation; the host does not transfer them twice.

The module `source_retention.spine_cc_host` builds the overlay from the frozen
image-source archive without changing that archive. Reproduction uses
`python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.spine_cc_host --archive <frozen-source> --output <new-directory>`
inside a 2-GiB zero-swap cgroup. The source archive root is
`/data/feiyang/spine-hls-cc-builds/cc-seele-import-20261016-v2/reused-inputs/inputs/source`.
The host ABI, source and binary receipt is local at
`/data/chuxiao/checks/source-retention-repair-20261104/spine-cc-resident-host-v1/manifest.json`.
The host linked directly against the XRT OpenCL library (no CUDA ICD loader),
built at 321 MiB peak with no memory events, and passed offline `--layout-only`
on the exact AU input at 134 MiB peak. These are not device timings.

`spine-cc-au-resident-wall-20261104.service`, invocation
`3744d99a43cb4d6b9fa3101b740d3385`, replaces the withdrawn job. It will request
the same 24-GiB/22-GiB zero-swap limits and 32-GiB reserve. Its output is
`/data/chuxiao/checks/source-retention-repair-20261104/spine-cc-au-board-v2/results.json`.
The runner admits one old-graph bootstrap and one 16-record batch. It checks
both timing windows, raw graph and labels, round work, and driver clock/UUID.
This is a Spine-only measurement, not a new speedup or an R admission result.

The existing sharded K4 CC host loads the batch and marks update-source active
bits before starting its timer. Its old number is therefore not a host-pack
comparison, and excludes baseline seed setup even if compared to Spine's
batch-resident window. A final paired result must expose and match the timing
boundary, or explicitly present an asymmetric, conservative bound. The old
publication-only Spine value is not suitable for this purpose.

### G+R Host For The Matching Wall Window

The opt-in G+R host in [HLS commit `2bbc636`](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/2bbc6361e879f5589b944271740ae08b98b162b0)
adds `GRASU_SHARDED_RESIDENT_BATCH_WALL=1` for SSSP, CC and ResPR without
changing kernel code. It times lane packing, update upload and migration,
host active-seed construction and upload for SSSP/CC, and execution to
convergence and final readback. ResPR retains the existing timed device
correction. The old timer remains available but has a different start.

The old G+R PMA is still built with knowledge of the batch: capacity
reservation, vertex ordering and external-to-physical update mapping are
before this window. The new timing record therefore says
`layout=trace_aware physical_update_mapping=offline`. Do not describe it as
latency from raw external-ID batch arrival, or use it to replace Figure 8.

Reproduction: use the commit above and build with
`scripts/build_weighted_pma_native_host.sh --pipeline-mode sharded-k4 --prefetch-compact --algorithm <algorithm> --out-dir <fresh-directory>`.
The runtime-plan unit test verifies that deferring update packing preserves
old graph bytes and reproduces identical update lanes. All four host
variants compile; AU SSSP, AU CC and the Flickr ResPR slice pass CPU
preflight with identical outputs in legacy and opt-in modes. FullPR and
repeated-update runs reject the option. The build and preflight ran under
a 2-GiB, zero-swap cap (peaks 319 MiB and 303 MiB). Logs and host hashes are
under `/data/chuxiao/checks/source-retention-repair-20261104/gr-resident-wall-host-v2/`.
The opt-in upload/seed path has not yet run on a board. The existing R
retention, G retention and first ResPR screen jobs still use their frozen
hosts; this host change does not replace or alter those controls.

The follow-up search of readable `/data/feiyang/spine*` and
`/data/feiyang/dynamic-acts*` paths found newer emulation files and 133-byte Git
LFS pointers named `*.hw.xclbin`, not a newer local routed image in those
paths. A pointer is not a loadable bitstream; its timestamp is not a build date.
