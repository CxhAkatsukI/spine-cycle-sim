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

The generalized-engine checkout also contains October-dated
`tiny-active.final172.hw.xclbin` and `tiny-active.scaled175.hw.xclbin`
entries under `openspec/changes/tiny-active-convergence-fast-path/artifacts/hw/`.
Both files are 133-byte Git LFS pointers; the adjacent `validation.md`
identifies their underlying hardware builds as July 9, not October builds.
On seele, the newest readable CC repair image found under
`/data/feiyang/spine-seele-cc-builds/` is
`cc-hw-20261016-v2/output/spine_partitioned_split_e2e.cc_repair.hw.xclbin`.
Its SHA-256 is the same `4071c0f7...e64c62` as the local candidate above,
so it is another copy, not a new revision.

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

The same matched host passed `--layout-only` on SU (567,316 vertices,
1,061,248 edges) and WK (1,140,149 vertices, 2,032,558 edges), with 16 signed
records each. The combined offline run peaked at 397.8 MiB. Its input pins
and logs are in `spine-cc-layout-{su,wk}-v3/` under the same check directory.

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

### Sparse Warm Insertion Repair

The old-image AU run above returned the exact state with no changed labels,
but took **7,886.354174 ms** from resident batch to final readback.
Admission/discovery consumed **7,116.419373 ms**, scanning 131,340 rows
and 669,796 edges; relaxation took **8.578485 ms**. The discovered rows
and edges are traversal counts, not the whole input graph size.
The [old-image raw receipt](spine-cc-au-resident-wall-v2.tar.gz) records
the one board sample and its timing boundary.

The [sparse CC repair](https://github.com/jayfeather9/spine-dynamic-graph/commit/c274abf)
starts pure insertions from the unique changed-edge endpoints of the old
converged state and lets decreases propagate through the existing worklist.
A separate bitmap preserves the exact count of distinct changed vertices.
Mixed and deletion batches retain the existing discovery/reset path. The
standalone and static-engine C-model tests pass, including cross-component
merges, repeated insertions, and deletion regression. This is functional
evidence, not an FPGA latency measurement.

The 150-MHz paper-geometry build is running on seele as
`spine-cc-warm-insert-route-20261104-v1.service` (invocation
`79463b9047ac4062810a42e50befc9aa`), with source and logs under
`/data/chuxiao/spine-cc-warm-insert-20261104-v1`. Its initial 40-GiB hard
cap was raised in place first to 48 GiB (44 GiB high) and then to 56 GiB
(52 GiB high, still no swap). At the second adjustment block-level synthesis
had completed 143 of 227 jobs, the route was using about 45 GiB anonymous
memory, and the host had about 321 GiB available with zero hard-limit or OOM
events for this route. The invocation is unchanged. The image and host must
be admitted together before measuring the same resident AU batch once. It
is not used in existing figure data.

The [native CC timing host](https://github.com/jayfeather9/spine-dynamic-graph/commit/79e7747)
adds the two old-arm wall windows: pack start or batch residency through
the same final label readback. It does not change the kernel. The hardware
host binary is `spine-cc-warm-host-v1/host_cc_repair` under the campaign
checks directory (SHA-256
`3f967b7ef10c0ce9bd44ac0ade280e464d7918d1e35a1242b9e690356f61ea10`).
Its offline check on the frozen AU input passed (`CC_LAYOUT_PASS`,
274,796,544 workspace bytes; 133.4 MiB service peak).

The local service `spine-cc-warm-au-return-and-board-20261105-v2.service`
(invocation `f4c8f198565343a9969d9fb02381c596`) waits for that exact route
invocation, verifies the image manifest and final timing/bus-skew reports,
and then calls the same `source_retention.spine_smoke --resident-wall`
runner as the old arm. It requests one batch with the same input manifest
and U55C lease, no timed warmup or retry, at 24 GiB hard / 22 GiB high /
zero swap with the runner's 32-GiB reserve. Local return evidence goes to
`spine-cc-warm-insert-return-v1/`; the board receipt goes to
`spine-cc-warm-au-board-v1/results.json`. At queue time the route was still
building. The result will diagnose the Spine repair only; it does not
compare Spine against a retention-qualified G+R.

If that AU arm succeeds, `source_retention.active_min_resident` can replay it
via `--cc-warm-au-receipt <results.json>` without another timed Spine launch.
Supply the CC wall packet with the exact warm image and host paths, the same
frozen split manifest, and the matched G+R wall host. Supply the distinct odd
Amazon and AU slice R receipts and input directories via
`--cc-warm-r-controls <odd-results> <odd-inputs> <au-results> <au-inputs>`,
in addition to the regular same-image Amazon R and G receipts. The runner
requires the same PCI card and CPU affinity as the retained arm. It records
one new G+R attempt, rechecks the retained raw Spine oracle and timing,
and compares the two pack-to-final-readback windows. It does not relabel
the cold-layout AU arm as a balanced-layout measurement or admit a pair
without all independent stage checks.

The [balanced warm CC host](https://github.com/jayfeather9/spine-dynamic-graph/commit/5c825f6)
adds the degree-balanced preload to the new native timing host. The
layout and device audit use the same hot bitmap. Comparing the complete
fingerprinted file set against the route's `79e7747` checkout found only
`host_cc_repair.cpp` and `cc_workload.hpp` changed. The host-only build
therefore embeds the verified route identity `85808e123f78044eee0905e0f87f19b41b338562f84d10fb200aac43249e5a3f`
via the host make target's `WEIGHTED_BUILD_SHA256` override; the route
and its original image manifest are unchanged. The build command is
recorded in local service `spine-cc-warm-balanced-host-build-20261105-v3.service`.
The resulting binary is `spine-cc-warm-balanced-host-v2/host_cc_repair`
(SHA-256 `aa265331a1e292dd8e2bd91d961bd9b3fdb2a1471aa29ba8983410313a223582`).

The AU and R19 frozen-input offline preflights both passed: AU has no
hot vertices; R19 has 23,913 hot vertices and 21,343,521 hot edges. Both
reserve a 16-record update margin. The two checks ran sequentially with
a 10-GiB hard cap and peaked at 5.6 GiB. For SO, PK, LJ and LJ08 the
offline campaign is `spine-cc-warm-balanced-large-layout-20261105-v1.service`
(invocation `8f1dc3e65e124de6af7675fa138bdac5`) with its journal at
`spine-cc-warm-balanced-large-layout-v1/results.json`; it starts only
with enough memory to honor its 24-GiB limit and 32-GiB host reserve.
These checks do not use an FPGA or provide latency measurements.

### Eight-Graph Preload Capacity

The repair host's current `cc_host::raw_slices` loads every family into a
single L1–L10 slot, leaving L0 available for the batch. L10 holds 8,388,608
edges per family. The fixed hot fixture rule sends destinations divisible
by three to the hot hash banks. That fixture rule is not a general
capacity planner.

The [offline occupancy probe](../../../../../../../cpp/tests/publication_sources/source_retention/spine_cc_occupancy.cpp)
compiled against the frozen CC host's `host_split.hpp` with the image's
compiler defines. It streamed the eight unchanged October graph files
after their SHA-256 checks passed, and reported the maximum number of
initial edges in a family:

| Graph | Current cold | Current fixed hot | Degree-based cold max | Degree-based hot max |
| --- | ---: | ---: | ---: | ---: |
| AU | 679,246 | 453,822 | 679,246 | 0 |
| SU | 1,061,248 | 691,054 | 1,061,248 | 0 |
| WK | 2,032,558 | 1,340,902 | 2,032,558 | 0 |
| SO | 23,803,759 | 15,882,674 | 8,388,584 | 1,310,143 |
| PK | 40,961,529 | 27,310,178 | 8,388,571 | 2,082,668 |
| LJ | 49,571,684 | 33,068,137 | 8,388,567 | 3,694,924 |
| LJ08 | 30,848,074 | 20,550,423 | 8,388,555 | 3,659,053 |
| R19 | 29,732,038 | 19,777,740 | 8,388,517 | 1,518,682 |

The five largest workloads exceed the existing loader's slot limit even
with its fixed hot rule. The alternative calls the already present
`partitioned_classify_hot_cold_from_indegree` with the L10 capacity
minus the 16 signed records as a conservative occupancy margin. It
does not change the vertex IDs, edges, weights, or batch. All eight fit
this initial occupancy check; the raw probe run took 53.2 s and peaked
at 196.9 MiB in a 2-GiB zero-swap service, without opening a card.

Raw TSV and checksum output: `/data/chuxiao/checks/source-retention-repair-20261104/spine-cc-eight-occupancy-v3/{occupancy.tsv,checksums.txt}`.
To reproduce, compile the probe from the matched host manifest's working
directory with its `-I`, `-D`, `-L`, `-Wl,`, and `-l` flags, verify
the CC graph SHA-256 pins from the October matrix configs, then pass the
eight graph paths in table order.

The opt-in CC repair host now uses this degree-based assignment. Build it
with `source_retention.spine_cc_host --balanced-preload` in the documented
2-GiB build service, and select it with `--hot balanced` for a single batch.
The same bitmap drives the preload family assignment, the metadata upload,
and the readback audit. Classification happens before the resident timer;
the bitstream, graph IDs, and batch are unchanged. The original cold and
fixed-hot modes remain available. The existing AU board smoke still uses
its frozen host; no AU performance sample was repeated.

The binary and build manifest are under
`/data/chuxiao/checks/source-retention-repair-20261104/spine-cc-balanced-host-v1/`.
The binary SHA-256 is
`c7f81eeb24cbabc13e6a28366370417106af2a2063c457c970fe171900fe1153`.
On AU, SU, and WK, `--layout-only --hot balanced --slice ... --update ...`
passed with a 16-record margin and an empty hot set, as expected. These
three checks ran without a card in a 2-GiB zero-swap service and peaked
at 397.8 MiB; their logs are under `spine-cc-balanced-layout-small.tTaoWI/`
in the same check directory. The default fixture still passes in the
old modes and rejects balanced mode because it has multiple batches.

The same host also passed `--layout-only` on the full R19 CC workload
(29,732,038 initial directed edges). The input manifest in
`spine-cc-r19-inputs-v1/` matches the October matrix source SHA-256.
It assigned 23,913 vertices and 21,343,521 initial edges to the hot set
with the same 16-record margin. The run took 2 min 2 s and peaked at
5.6 GiB in a 12-GiB zero-swap service, with a shared compiler-memory
reservation and a 32-GiB live-memory floor. The admission record, result,
and raw logs are in `spine-cc-r19-balanced-layout-v1/`.

For SO, PK, LJ and LJ08, run the remaining host layout checks through
`source_retention.spine_cc_layout` (under the same module prefix as
`spine_cc_input`). Pass `--matrix <frozen-matrix> --datasets so pk lj lj08
--wait-seconds 86400 --output <inputs>` in a 2-GiB zero-swap service. The
runner streams the native host inputs and verifies the frozen matrix hashes.
Run it again with the same matrix and dataset arguments, a fresh
`--output <layouts>`, `--inputs <inputs>`, and `--host <balanced-host>`,
in a 24-GiB zero-swap service. Both services require a finite
`MemoryHigh`, `OOMPolicy=kill`, and a shared memory reservation that leaves
32 GiB available beyond all admitted budgets. The layout service waits for
the complete preparation receipt and then checks the four layouts one at a
time. The current outputs are under
`/data/chuxiao/checks/source-retention-repair-20261104/spine-cc-large-{inputs,layout}-v1/`.

The occupancy probe and offline host checks do not validate device carry,
convergence, or board wall time. The board still needs to pass graph
readback, label, and convergence checks before any timing is admitted.

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

For the active-Min CC and SSSP candidate, the same host-only change is
applied to the exact fixture source in
[commit `15717a5`](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/15717a5928929cafd39dbf5a3f7fc1aaf18d167a).
It preserves the fixture and update-only modes when the wall option is
off, and makes no kernel or connectivity change. The binaries and CPU
preflight are under
`/data/chuxiao/checks/source-retention-repair-20261104/gr-active-min-wall-host-v1/`.

| Host | SHA-256 |
| --- | --- |
| Weighted SSSP | `265bf7f190e2eff8be99fd63597d59f1a436ba71faa84fb22526c645d7888d3a` |
| CC | `b72c20fec3bc7130edf430ff0006963e3112dfa57ea31bc96e38246b303f7412` |

Both hosts preserve the full AU prepare-only output with the option off
and on, and preserve the full Amazon source-retention preparation output
and reference bytes with it off. This took 24 s and peaked at 1 GiB in a
2-GiB zero-swap service. These are CPU checks, not validation of the
board uploads or a substitute for the frozen R/G admission receipts.

`cc_resident_results.py` checks a single resident CC log pair, requires
both host-pack timers and successful per-arm oracles, and reports
`G+R ms / Spine ms` even below one. It requires the caller to verify
the input, image, clock and board pins separately. It does not accept
the old G+R timer or the Spine-only smoke as a paired result.

### Gated Full R19 CC Pair

`source_retention.active_min_resident_follow --cc-wall-packet <packet.json>`
binds the two wall hosts, the Spine repair image, and the split-input
receipt to the original R19 workload. The packet fields are
`spine_host`, `spine_binary`, `gr_host`, and `inputs` (the split receipt
from `source_retention.spine_cc_input`). It verifies the raw input hash,
the dimensions and both serialized input hashes before waiting.
The frozen packet is at
`/data/chuxiao/checks/source-retention-repair-20261104/cc-r19-wall-packet-v1.json`.

Service `gr-retention-cc-resident-r19-wall-20261104.service` waits for the
exact CC R and G stage jobs. A successful producer status alone does not
admit the pair: the resident runner replays both raw gates and uses the
same admitted G+R image and clock. It requests one sample per arm, no
timed warmups or retries, on U55C `0000:c1:00.1`, with a 32-GiB cgroup
cap, 30-GiB high watermark, zero swap, and a separate 32-GiB live reserve.
The wall starts at batch packing after old-state bootstrap and stops at
final label readback; the G+R pre-reserved layout and offline update
mapping remain outside it.

Queue and later raw pair receipts:
`/data/chuxiao/checks/source-retention-repair-20261104/cc-r19-resident-wall-v1/`.
At enqueue both producers were active and the board had not been requested.
This is one conditional workload, not evidence that either gate passed
or that a new Fig. 7 result exists.

### Earlier Remaining-Seven CC Queue

`source_retention.cc_matrix` binds the same balanced Spine image and
resident-wall host overlay to the other seven frozen CC workloads. It
requires independently passing G, ordinary A4 R and high-active/odd
A4 R hardware screens on the exact candidate image and driver clock.
The R19 pair is indexed separately and is never repeated by this queue.

AU, SU and WK reuse their completed offline layout checks. SO, PK, LJ
and LJ08 require matching terminal layout receipts from
`spine-cc-large-layout-v1/`. A missing or failed layout is reported
instead of triggering a smaller substitute. After admission the board
children run sequentially, with one sample per arm, no warmup or retry,
and the same 32-GiB cap, zero swap and 32-GiB live reserve as R19.

Service `gr-retention-cc-matrix-20261104.service`, invocation
`5ab92934aa0f444db875ed801d3c2322`, writes its stage and input pins, exact
child commands, and per-case outcomes to
`/data/chuxiao/checks/source-retention-repair-20261104/cc-singlepass-matrix-v1/matrix.json`.
At enqueue, the three small layout records were verified and no board
child was requested. This is not a new speedup or evidence of G/R
retention.

The follow-up search of readable `/data/feiyang/spine*` and
`/data/feiyang/dynamic-acts*` paths found newer emulation files and 133-byte Git
LFS pointers named `*.hw.xclbin`, not a newer local routed image in those
paths. A pointer is not a loadable bitstream; its timestamp is not a build date.

The November 4 HOT12 link on Seele is also not a board image. The project
record at `/data/feiyang/spine-dynamic-graph-generalized-engine/openspec/changes/generalize-incremental-compute-engine-hls/execution-status.md`
on trifoliate identifies the 469,682,090-byte output as `hw_emu` and
explicitly reports no FPGA card use. The adjacent
`seele-rootless-hot12-link-plan.md` records image SHA-256
`41aa16009b9318890e49b3243721de10a6400d6aaa54df43a4d443aaa8148b92`.
The original HOT12 emulation hit a bootstrap epoch audit before applying any
updates. The private remote build directory was not independently inventoried;
this finding excludes the documented HOT12 image, not every possible private
build. The previously verified image remains the old-arm control; see
[current board queues](REMOTE_LINKS.md#current-one-shot-board-queues)
for the stopped old-image matrix and the separate warm-insertion check.
