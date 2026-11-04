# R Hardware Retention Repair

## Latest Checkpoint

No current image has passed both G and all declared R hardware controls
for its algorithm. These are the latest relevant measured checkpoints;
numbers are elapsed-time changes from each matched public control.

| Algorithm | R-only FPGA screen | Independent G and next image |
| --- | --- | --- |
| Weighted SSSP | Latest nominal source-burst image: Amazon **-5.54%**, high-activity Amazon **-6.18%**, AU **+21.43%**. | G on this exact image passed (**-60.27%** on AU 131K); the failed AU R gate prevented resident tests. |
| CC | Four-bank image: Amazon **+0.66%**, high-activity Amazon **-6.82%**, AU **+20.92%**. | The four-bank image passed G (**-61.65%** on AU 131K). Its source-burst replacement needs separate G and R screens. |
| ResPR | Packed-validity image: Amazon **-4.22%**, skewed-source **+15.73%**, a miss of **3.871 us** at nominal clocks. | G on that image took **133.500 ms** against **18.369 ms**. The degree-prefix replacement addresses this G path and needs separate G and R screens. |

See the [nominal SSSP board receipts](SSSP_STAGE_ADMISSION.md#nominal-source-burst-board-screen),
[CC board receipts](REMOTE_LINKS.md#cc-banked-clear-board-checkpoint),
[same-clock R screens](LOWER_CLOCK_SCREEN.md#measured-pairs),
and [independent G receipts](G_SCOPE.md) for input, host and bitstream
provenance. Resident convergence queues require the new exact-image
stage gates. Each new arm is measured once, under a board lease and
memory admission with no swap.

The [same-card AU/512 setup replay](FIGURE_IMPACT.md#two-bank-spine-host-replay)
measured **701.928 ms** for the revised Spine host versus **848.316 ms**
for the independently qualified G path (**1.21x** Spine speedup). It
reuses the measured G arm and is a single update-only workload, not an
R gate or a replacement for Figure 8.

The [Spine CC warm-insert repair](SPINE_ARTIFACTS.md#sparse-warm-insertion-repair)
passed the one-shot full AU correctness check. Its resident window fell
from **7,886.354 ms** to **17.516 ms**. This compares two Spine images on
the same workload; no G+R arm has been timed against this Spine image yet.

ResPR returned images use the qualified card at `0000:82:00.1` for the
nominal screen, with measured 150/500/450/0 MHz required around each arm.
If the vendor lowers only HBM, a separate diagnostic accepts a candidate
only in the same physical clock bin as an existing correctness-checked A4
record (430 MHz CC; 430 or 445 MHz ResPR). It replays the reference
receipts and times only the new candidate. A lower-clock result does not
admit the nominal resident matrix.

See [Figure Impact](FIGURE_IMPACT.md) for the frozen Fig. 7 audit. Two wins
survive even a zero-cost R; nine survive an ideal full K4 scan with
unchanged G and Spine. Keeping the current span reader's required
directory traversal preserves 12 directions; 12 remain undetermined.
This checkpoint is not a replacement Fig. 7--11 package.

## Acceptance Order

This study continues the failed [source-retention control](../source_performance_retention_20261103/README.md).
It does not promote that control, change the paper, or overwrite frozen figure
packages. Simulator near-parity is not FPGA performance admission.

The [seele replacement links](REMOTE_LINKS.md) record the routed attempts
and their independent return checks; they are not new timings. The
[ResPR Apply retime](REMOTE_LINKS.md#respr-apply-input-retime) removes the
observed critical-path structure in generated RTL. Integrated timing and
stage-retention measurements are still pending.

The [weighted SSSP FPGA stage screen](SSSP_STAGE_ADMISSION.md) passed
independent G and both Amazon R controls on the same returned image.
The same image missed the 15% R gate on the AskUbuntu topology control
(19.55% slower). Treat the paired convergence timings as observations
on that image, not as a matrix against a cross-topology-validated baseline.
The [resident SSSP follow-up](sssp-resident-followup/README.md) adds R19
PK and SO, retaining the three original measured pairs without repeating them.
The [source-read burst retry](SSSP_STAGE_ADMISSION.md#source-property-read-burst-repair)
has synthesis evidence, a [445-MHz HBM board diagnostic](SSSP_STAGE_ADMISSION.md#matched-445-mhz-hbm-diagnostic)
and an exact-image nominal board queue. Its first resident pair is gated
on G plus all three R controls.

The [first tail-repair board diagnostic](R_PUBLICATION_WINDOWS.md#tail-repair-derated-fpga-diagnostic)
is now available. Full Amazon is within 1.2% of the public A4 in raw
elapsed time; the skewed control is still 87.5% slower. The candidate's
HBM was derated, so this is not same-clock baseline admission.

The [same-clock board screens](LOWER_CLOCK_SCREEN.md#measured-pairs)
retain the per-image timings, actual clock vectors and gate decisions.
Do not use the 445- and 430-MHz ResPR arms as a direct before/after
measurement of a component change.

1. Freeze the production source, bitstream, host, graph and numeric policy.
2. Diagnose and repair the actual adapter/R implementation. Keep the original
   A4 reference and the pre-repair measurements. Screen each new matched case
   once, with full correctness checks; do not start a repeated full matrix.
3. Admit R only when current/reference resident elapsed time is at most 1.15
   on every declared supported control. Record unsupported cases explicitly.
   The initial controls are skewed-source and full Amazon. The duplicate-edge
   boundary-ring input remains unsupported, not silently deduplicated.
4. Verify G independently for the exact integrated image. The four earlier
   AU controls cover the weighted-SSSP image only; see
   [G evidence and pending checks](G_SCOPE.md) for the different CC and ResPR
   update kernels. An R-only pass does not admit either of those G paths.
5. Inventory Spine artifacts under `/data/feiyang`, verifying source, ABI,
   correctness and measured clocks rather than selecting by filename/mtime.
6. Compare validated G+R and Spine from the same old-graph converged state,
   raw batch and stopping rule. Screen each eight-graph/three-algorithm case
   once. Optimize measured bottlenecks without hiding losing cases.
7. Bound the impact on prior Figures 7--11 using measured stage envelopes,
   or rerun affected experiments. Deliver data, provenance, analysis/code and
   README together. Stage predictions stay labeled predictions.

## Initial Source-Backed Findings

Read the [comparison contract and resource differences](COMPARABILITY.md)
before interpreting a timing ratio. Four Little frontends do not establish
identical state-memory resources, arithmetic, or convergence semantics.

The actual ResPR bitstream is
`c112e790c3cfd81c05b4059f1dc34fcee23bc36a94a995ba1c0d6d49280058c0`.
Its packaged source already contains the optimized prefetch/compact adapter;
the 12.77x Amazon slowdown cannot be dismissed as an old adapter measurement.
The producing HLS worktree starts at
`dec40633c5802465680e39bd375ab0d86a4ab5aa`.

The 2026-10-24 HLS reports in
`/data/chuxiao/builds/gr-prefetch-blocking-axis-trif-20261024/respr/`
show:

| Component | Requested | Synthesized | Evidence |
| --- | --- | --- | --- |
| Adapter row traversal | II=1 | Outer row loop is not pipelined; nested segment loop restarts | `join_segments_csynth.rpt` |
| Framed Scatter | II=1 | II=2 | FIFO-full query followed by blocking write creates a carried dependence |
| Framed Gather | II=1 | II=3 | Binary32 forwarding/reduction has a real carried dependence |
| PR Apply burst loop | II=1 | II=1, depth 163 | Depth is latency, not an initiation interval of 163 |

These are implementation findings, not an additive attribution of the whole
slowdown. In particular, stream event times include backpressure. No invented
timing multiplier or false dependence directive may erase a real hazard.

## Repair-Before Screening

The [portable checkpoint](before-once/manifest.json) contains
[comparison data](before-once/data/comparison.csv),
[raw logs and paired host build](before-once/evidence/raw_board.tar.gz), and
[probe source](before-once/evidence/reproduction_sources.tar.gz).
Inputs remain in the previous control's frozen input archive, indexed by
the full SHA-256 identities in `before-once/data/artifacts.json`.

| R control | Reference ms | Current ms | Current/reference | Decision |
| --- | ---: | ---: | ---: | --- |
| Skewed sources | 0.461233 | 1.361358 | 2.95156 | Fails 1.15 gate |
| Full Amazon | 10.365434 | 70.254409 | 6.77776 | Fails 1.15 gate |
| Boundary ring | -- | -- | -- | Unsupported: 64 duplicate edges |

Each supported arm executes **once**, with no warmup or average. Both hosts
use GCC 15, C++20, `-O2 -DNDEBUG`, the same XRT library, affinity `124,125`,
and the same leased U55C at PCI address `0000:c1:00.1`. This is a matched
single gather/apply superstep, not an updated-graph convergence comparison.
The reported time is first CU start to last CU end, including any internal
host gaps; initial input residency, state restore and result readback are
outside both arms. Full correctness and timestamp-envelope replay pass.

The earlier 3.69x/12.77x values use three warm repetitions. They remain in
the earlier package, but must not be spliced into this single-run comparison
or interpreted as evidence that a kernel became faster. The SSSP-only G rows
are replayed from that frozen campaign, not remeasured or averaged again.

The repair-before checkpoint did not capture per-run driver clocks. It is
retained as a failed diagnostic, not promoted to frequency-matched admission.
The updated runner archives `xclbinutil` image metadata and, after each host
exits under the same exclusive lease, the resident UUID and raw sysfs clock
readings. Analysis checks the image match and replays these records. It keeps
the observed frequencies and raw elapsed-time ratio: it does not silently
replace driver readings with the requested 150 MHz or normalize time by a
frequency factor. These queries are outside the measured event window.

The [ordered publication diagnosis](R_PUBLICATION_WINDOWS.md) replays
the archived once-per-arm timestamps. It localizes the old Amazon delay to
specific shard windows and records which upstream images can serve as
matched hardware controls.

## Implemented Repair

HLS commit [`24519a6`](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/24519a6)
introduces a finite descriptor FIFO and a flat segment reader. Each directory
line supplies eight bounds; empty rows are skipped from a local mask, while
nonempty row spans preserve source identity and exact segment credits. This
removes per-row segment-loop restarts without dropping padding traffic,
changing the graph, increasing the port budget or changing arithmetic.

| Gate | Result | Evidence on trifoliate |
| --- | --- | --- |
| C simulation | Weighted, destination and unit modes pass 198 cases each; all 65,536 compact masks and 4,096 randomized checks pass | `/data/chuxiao/checks/pma-directory-spans-20261103-v2/` |
| Adapter synthesis | Pass; descriptor/segment loops achieve II=1, estimated Fmax 199.01 MHz | `/data/chuxiao/builds/gr-directory-spans-20261103/respr/evidence/adapter/` |
| Finite random-stall RTL | Pass all eight cases, including empty rows, tile boundaries and backpressure | `/data/chuxiao/builds/gr-directory-spans-20261103/respr/evidence/rtl-destination/` |
| Full ResPR link | Running at the checkpoint; **not yet board-tested** | `/data/chuxiao/builds/gr-directory-spans-20261103/route-respr-v1/` |

The replacement retains all eleven other production XOs and the exact
connectivity. The adapter XO SHA-256 is
`e0e979370b8cebfc19d50b24a54f74846709bc9e96a94e15f0124295ce2c6358`.
The source packet was prepared from `dec40633` plus the now-committed repair;
its `inputs.tsv` and each gate's `manifest.json` pin the actual file contents.
No synthetic timing coefficient or predicted speedup is used as admission.

Weighted SSSP and CC each passed adapter synthesis and all eight finite
random-stall RTL cases. The per-algorithm evidence directories are
`/data/chuxiao/builds/gr-directory-spans-20261103/{sssp,cc}/evidence/`;
neither run recorded a cgroup limit or OOM event. The ABI-checked eleven-XO
relink manifests are `route-{sssp,cc}-v2/manifest.json` under that build root.
They retain all ten other XOs and the frozen connectivity. Their guarded
launchers are queued; the active ResPR link still has the full-link memory
lease.
These are component results only: the existing measured four-Little R
control uses PageRank arithmetic and cannot admit the weighted-SSSP or CC
resident R path.

The separate [active-min A4 host](../../../../../../../cpp/tests/original_regraph/hardware/active_min/README.md)
now compiles with XRT and passes both offline policy fixtures. It also
validated the archived Amazon author task/CSR edge multiset. The CC and
weighted-SSSP author controls still need their own routed images with a
writable Apply property buffer; the PR control image cannot be reused.

The [A4 source preflight](../../../../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/source_build/README.md)
now generates separate CC and weighted-SSSP compile/link plans. Both preserve
the four Little lanes and bind writable Apply state to HBM 30. All eight
translation units passed host compiler syntax checks using the Vitis 2024.1
headers. This is source-only evidence; no new XO, routed image, or timing
measurement is admitted by the preflight.
The guarded source-build runner now uses the same compile/link planner and
records separate routed statuses for CC and weighted SSSP. Neither status can
be admitted by the PR board gate. The public input audit is checked before
compilation; it does not establish active-min board correctness.
The separate
[A4 active-min reference runner](../../../../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/board_execution/README.md)
checks the routed image and runs one superstep, retaining offline CSR
expectations, all published buffers, the resident image UUID and raw event
timestamps. The CC and weighted SSSP offline fixtures pass through this
runner; a new FPGA measurement still requires the corresponding routed image.

The archived full Amazon graph (735,324 vertices; 5,158,388 logical edges;
48 A4 tasks) now also has independently checked active-min component inputs.
The CC and weighted SSSP oracles both report 10 improved vertices from the
same single-source fixture. Input hashes, raw oracle output and the exact
geometry are in
`/data/chuxiao/checks/source-retention-repair-20261104/a4-active-amazon-v2/`.
The preparation used a 2-GiB zero-swap cap and peaked at 255.3 MiB.
The archived skewed-source capture publishes 65,536 of 65,537 logical
vertices; its active-min rejection is retained under
`/data/chuxiao/checks/source-retention-repair-20261104/a4-active-skewed-v1/`.
That capture remains eligible for the separate historical PR control only.
The active-min inputs use one synthetic resident superstep. The
[integrated candidate host](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/57888d6/docs/sharded_k4_prefetch_compact/active_min_retention.md)
now loads the same fixture through the production sharded PMA preparation
path. Both full-Amazon policies independently match the A4 oracle byte for
byte over all 786,432 aligned property words, and yield 10 improved vertices.
The A4-only 16-word overrun guard is validated separately. The four existing
native-host preprocessing checks also pass. The candidate outputs are in
`/data/chuxiao/checks/gr-active-min-candidate-20261104-v1/`.

The new host has not run on a board. The [paired runner](../../../../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/board_execution/README.md#active-min-a4-and-sharded-k4-pair)
is ready to run one reference and one candidate on a single leased U55C. It
checks the published states and matching driver clocks and retains the raw
kernel timestamps and the 1.15x acceptance result. Corresponding routed
images and paired measurements are still needed; neither the offline agreement
nor the older PR probe establishes CC or weighted-SSSP latency retention.

The full link has a 40-GiB hard limit, 36-GiB high watermark and a six-hour
timeout. Each SSSP/CC component service has an 8-GiB limit and 7-GiB high
watermark; these are component-only budgets based on the observed ResPR
compile/RTL peaks, not full-link budgets. All jobs have zero cgroup swap,
an atomic full-budget reservation, and a 40-GiB live-memory watchdog reserve.
Admission and resource samples are retained. The C/RTL passes are **not**
proof that the FPGA performance gate passes.

## Reproduction

From the simulator worktree, the paired Release hosts are built with:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.build \
  --repository /home/chuxiao/spine-cycle-sim/spine-cycle-sim-fullgraph-evidence \
  --integration /home/chuxiao/grasu-regraph-sim-aligned \
  --output /data/chuxiao/checks/source-retention-repair-20261104/hosts-pinned
```

Fresh output directories are required. The exact four board commands,
input/bitstream hashes and cgroup policy are archived in
`before-once/evidence/raw_board.tar.gz`. The R-only study uses
`source_retention.study --stages R --r-single-run`; the default historical
four-run behavior remains reproducible. Analysis and packaging use:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.analysis \
  --g-results /data/chuxiao/checks/source-retention-20261103-v1/campaign-v1/results.json \
  --r-results /data/chuxiao/checks/source-retention-repair-20261104/before-once/results.json \
  --output /data/chuxiao/checks/source-retention-repair-20261104/before-analysis-v1
```

The separately owned `directory_tile.hardware.component` and
`directory_tile.hardware.replacement` modules freeze generated source pins,
verify finite RTL/synthesis and ABI compatibility, and replace only the
adapter. Their exact invocation is recorded in each execution manifest.

### Adapter-Only Performance Floor

The running replacement keeps the production gather and frontend mux. In
the [matched board host](../../../../../../../cpp/tests/publication_sources/source_retention/device.hpp),
the first gather must initialize, every destination shard emits 32,768
two-destination packets, and mux task `s` waits for mux task `s-1`.
The framed gather in the frozen HLS source clears 32,768 URAM rows before
it can consume the first shard and publishes only after consuming the
terminal input packet. The frontend mux has one 64-bit output stream and
can forward at most one packet per cycle. The production
`gather_csynth.rpt` reports 32,770 cycles for each of the initialize and
read/clear loops; use 32,768 for a conservative bound.

Counting **only the first reset and the serialized mux output** avoids
double-counting the gather output or resets on other workers:

| R control | Shards | Minimum cycles at a common clock | Floor at 150 MHz (ms) | Gate (ms) |
| --- | ---: | ---: | ---: | ---: |
| Skewed sources, 65,537 vertices | 2 | 98,304 | 0.655360 | 0.530418 |
| Full Amazon, 735,324 vertices | 12 | 425,984 | 2.839893 | 11.920249 |

The gate is 1.15 times the corresponding one-run reference time in the
repair-before table. At 150 MHz, the skewed-source floor alone is 1.421
times the reference, even with zero adapter, scatter, apply and runtime
overhead. Ignoring those costs, it would need at least 185.33 MHz at a common
clock to meet that reference. With separate clocks use
`32768/f_gather + shards*32768/f_mux` and recompute against the newly
measured reference. The calculation rules out adapter-only parity at the
declared clock and reference for the skewed control; it does not predict an
Amazon pass or fail. The pending board screen still checks both clocks and
both elapsed times.

The [pre-repair raw events](before-once/evidence/raw_board.tar.gz) also show
that adapter and gather completion are not interchangeable. On skewed shard
1 the adapter event lasts 0.085 ms and gather ends 1.026 ms after it; on
Amazon shard 7 gather ends 10.918 ms after the adapter. In those logs,
ordinals `2+3*s`, `3+3*s`, and `4+3*s` are adapter, gather and mux for
zero-based shard `s`. These are overlapping elapsed intervals with FIFO
backpressure, not exclusive busy-cycle measurements.

### Tail Publication Candidate

HLS commits [8df36e5](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/8df36e5)
and [b8b08ff](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/b8b08ff)
implement aligned tail publication for ResPR. The last skewed shard has
one valid vertex: its mux count becomes eight packets, down from 32,768.
The same floor then falls to 65,544 cycles (0.436960 ms at 150 MHz), which
no longer rules out the 0.530418-ms gate. It leaves only 0.093458 ms above
the floor for all additional costs; it is not a prediction that the gate
passes. On full Amazon this change only shortens the final shard and
cannot explain or remove the whole observed gap.

The Vitis 2024.1 component XO is
`/data/chuxiao/builds/gr-tail-publication-20261104/packet-v1/build/lksg_stream.hw.xo`
(SHA-256 `909a51a7aef6d53d66caa3c97b4da0ed86f43c43a8498ef576793232dae9e6d6`).
The matched host build uses `source_retention.build --tail-publication`;
its compile commands and hashes are in
`/data/chuxiao/checks/source-retention-repair-20261104/hosts-tail-v1/manifest.json`.
The new scalar is argument 5; the old image uses that position for a
stream, so the matching tail image is required. The test input, expected
output, event boundaries and fixed-length reference are unchanged.
The C simulation, gather synthesis and host compile are complete. The
whole-board packet uses the separately pinned
`/data/chuxiao/builds/gr-tail-publication-20261104/packet-v2/build/lksg_stream.hw.xo`
(SHA-256 `54c31a68ed67ab2772d7fc4edd03e0d1d0eeba65a3262d306ecfa9fb31d69943`).
Preflight checked the gather interface and compiler flags, the matching host
pair, and that only adapter and gather change among the twelve XO files.
The production link configuration is unchanged; the completed production IP
cache is copied to the new link directory and pinned. The link service waits
for full cgroup memory admission. The once-per-arm screen follows that exact
service invocation and records its result under
`/data/chuxiao/checks/source-retention-repair-20261104/tail-follow-v1/`.
Neither preflight nor the component XO constitutes a board result.

If both R controls pass, the matching native host checks G once on AU
with the same public-source reference and device-update boundary. The
production host is rejected for the tail route. The build manifest for
this native host is
`/data/chuxiao/builds/gr-tail-publication-20261104/native-host-v1/manifest.txt`.
The dependent R19/Flickr Spine screen is admitted only after both G and R
pass on this exact image, board, and actual clocks; it does not run a
full matrix. The two board reports are `g-tail-board-v1/results.json`
and `resident-tail-board-v1/results.json` under the same check directory.

The local tail link stopped at memory admission without starting a board
measurement. A separate, sealed return of the same plan can be consumed by
`source_retention.follow --returned-candidate RETURNED CAPSULE XPFM`.
The follower verifies the completed collector, local plan, source pins, routed
timing and nominal 150-MHz topology before requesting the two one-shot R pairs.
The unchanged local plan remains the input to the native G runner; it checks
the returned admission against the raw R report's exact loaded image. An
accepted link is not a performance result. The remote-route R and G outputs
are kept separately from the local attempt under `tail-follow-seele-v1/`
and `g-tail-seele-v1/`.

### Timeout Recovery

The preceding production ResPR link took 5 h 49 min even with a seeded
IP cache. The first repair link hit its six-hour watchdog in Vivado route
phase 5.1 (global iteration 0). Its receipt reports `stop_reason=timeout`,
`cleanup_snapshot_error=null`, and a sampled process-tree peak of
33,792,992 KiB. The service stopped with no workers and no candidate image;
the dependent board screen therefore took no sample. The timeout qualified
for a separate attempt with the same link command (except output paths)
and a twelve-hour deadline:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.cached_retry \
  --previous /data/chuxiao/builds/gr-directory-spans-20261103/route-respr-v1 \
  --output /data/chuxiao/builds/gr-directory-spans-20261103/route-respr-cached-v2 \
  --unit gr-directory-spans-route-20261104.service \
  --invocation 84845edf6b294efb8f856df572d2a341
```

The new invocation is `gr-respr-cached-route-v2-20261104.service`
(`6f1625b870d74ac0b187aca31dfb9b43`). It starts with
`--output ... --execute --admission-wait 21600`, 40/36-GiB hard/high
limits, zero swap, and a 19-hour service runtime (six hours of possible
admission wait plus the twelve-hour link and margin). Admission and the
live-memory watchdog are unchanged. Cache entries are copied and hashed;
Vivado still selects entries using its own fingerprints. A successful original
attempt, an active build, a memory stop, or an unexplained failure does not
qualify for this retry.

The `source_retention.cached_screen` companion watches the live retry
invocation and its cgroup, then verifies the exact command, plan and image
in the terminal route receipts. It runs R once per supported arm and tests
G once on the same image against its independent resident control, even
if a correctness-admitted R result misses the performance threshold. Its
R and G reports are separate (`after-cached-respr-v2/results.json` and
`after-cached-respr-v2/g/results.json` in the same check directory).
No full-graph Spine campaign is authorized by this job alone.

### Board Screening

The bounded continuation below waits for the exact route service invocation,
checks the completed image and its source pins, then screens the same two
supported controls once per arm. It captures driver clocks and writes a
portable checkpoint under `after-follow-v2/delivery/`, even if the performance
gate fails. It never starts the full evaluation matrix automatically.

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.follow \
  --before /data/chuxiao/checks/source-retention-repair-20261104/before-once/results.json \
  --route /data/chuxiao/builds/gr-directory-spans-20261103/route-respr-v1 \
  --g-results /data/chuxiao/checks/source-retention-20261103-v1/campaign-v1/results.json \
  --hosts /data/chuxiao/checks/source-retention-repair-20261104/hosts-pinned \
  --production /home/chuxiao/grasu-regraph-sim-aligned \
  --output /data/chuxiao/checks/source-retention-repair-20261104/after-follow-v2 \
  --unit gr-directory-spans-route-20261104.service \
  --invocation 84845edf6b294efb8f856df572d2a341
```

Run this continuation inside an 8-GiB maximum, 7-GiB high-watermark,
zero-swap cgroup. Its wait is bounded to six hours; each host invocation is
bounded to four minutes. A changed or failed route cannot request the board.
The initial continuation attempt (`after-follow-v1`) stopped before any board
request because its pin comparison expected a byte count absent from build
manifests. The runner now checks the declared path/SHA-256 and, where present,
byte count; it still rejects changed contents. The failed attempt is retained.

### Matched Amazon CC And Weighted SSSP Screens

| Algorithm | Public-source A4 build | Integrated K4 build | Board queue |
| --- | --- | --- | --- |
| CC | `public-a4-cc-v1` (`daebd3a0b01e4abdb77521e4637a7a2e`) | `route-cc-v2` (`7a7ef5ecb10c4d2ebcea983b3b8d2da3`) | `cc-active-pair-v1/queue.json` |
| Weighted SSSP | `public-a4-sssp-v1` (`ddbeaa29a93341ef826f415a00406ef7`) | `route-sssp-v2` (`984d35fd03134d0bb02b5aaf30594ffd`) | `sssp-active-pair-v2/queue.json` |

Build directories are under `/data/chuxiao/builds/gr-directory-spans-20261103/`;
board queues are under `/data/chuxiao/checks/source-retention-repair-20261104/`.
Each build uses the shared compiler-memory admission lock and a 40-GiB maximum,
36-GiB high watermark, zero-swap cgroup. The initial integrated `v1` launchers
were rejected before starting Vitis because their requested wait exceeded the
replacement driver's six-hour limit. Their logs are retained; the `v2` launches
use a six-hour wait. The initial SSSP pair did not request the board.

Both public controls use four Little lanes and no Big lanes. Weighted SSSP
uses the explicitly identified local weighted UDF at
`/home/chuxiao/regraph/ReGraph/acc_udfs/sssp/l2.h`; it is a matched arithmetic
control, not an unmodified publication workload. Each pair pins both build
invocations and waits without holding a board lease. After successful routes,
it runs each arm once from the same resident Amazon active state, checks both
outputs against the same oracle, and compares elapsed R device event spans
against the 1.15 ratio. The gate also requires equal driver-reported clocks.
A failed or replaced route is not admitted.
This is a single superstep, not a G timing measurement, an eight-graph matrix,
or a convergence experiment.

The A4 host was relinked directly against the same XRT OpenCL library as the
integrated host. The previous binary resolved a generic loader from the CUDA
installation. Relinking preserved the full-Amazon offline oracle hashes for
both CC and weighted SSSP. The paired runner checks the resolved library digest
before queueing and again under the board lease. This is a preflight, not a
measured R retention result.

#### High-Activity Amazon Control

The single-source fixture has only ten improved vertices. Before seeing any
new FPGA timing, a second fixture was frozen on the same author A4 task
layout and CSR. It starts all odd external vertex IDs active at value zero;
inactive CC vertices start at their own labels, and inactive SSSP vertices at
infinity. Graph layout, SSSP weight rule, publication extent, and one-superstep
boundary stay fixed. It tests high activity, not convergence or another dataset.

Generate it with `active_min_inputs --frontier odd-vertices`. The local
receipt is `a4-active-amazon-odd-v1/manifest.json` under the board queue root
above (SHA-256
`81e9430421d52acf665a507f808a7f467f745818f491aa7dc1fc605ae95e9add`).
It records 367,662 active sources on 735,324 vertices and 5,158,388 edges.
The author control and native K4 offline replay agree bit-for-bit across all
786,432 published words, including padding; the author output has an
additional 16-word guard. CC and weighted SSSP improve 315,862 and 315,863
vertices, respectively. Native outputs are retained in
`a4-active-amazon-odd-v1/{cc,weighted_sssp}-native/expected.u32le`.

After the primary screens, use the same routed image pair per algorithm and
run each arm once, with the same output, clock, and at-most-1.15 latency-ratio
gates. The `active_min_follow` runner takes `--odd-fixture MANIFEST SHA256`,
two `--after-pair UNIT INVOCATION JOURNAL` dependencies on the primary
screens, and a bounded `--board-wait-seconds`. It preserves the primary
receipts even when an R ratio fails, checks the frozen input hashes, and
serializes board use. It releases its 8-GiB memory reservation when the card
is busy and does not retry any measured arm. This fixture has offline
correctness evidence only; it is not a performance result.

## Remaining Gates

Goal active: complete the route, check actual clocks and measure the new
bitstream once against the same reference/hosts/inputs. If it fails 1.15,
retain the result and diagnose the remaining input/scatter/gather bottleneck.
Do not start a replacement full matrix merely because the build passes.

The [Spine artifact inventory](SPINE_ARTIFACTS.md) separates the images used
in the October 26 matrix from later component-repair candidates. The later
CC candidate passed a single on-board canonical correctness and clock check.
Large-graph performance admission, paired convergence runs, impact bounds
and final figure/data delivery remain open. The
[figure dependency audit](FIGURE_IMPACT.md) identifies
which frozen results are exposed to the R repair, including the correction
pass in all eight zero-propagation ResPR cases. Nothing in this checkpoint
supersedes Figures 7--11.

The [paired ResPR screen](RESIDENT_SCREEN.md) freezes the first two
post-admission inputs and provides the gated, single-run board command. It
preserves the old matrix's narrowest ResPR win and adds an independently
preflighted nonempty-propagation case. Neither is a new FPGA timing
measurement.

## Checkpoint Verification

The focused build, replacement, retention, clock-record, packaging, candidate
smoke and repository-organization suites pass 48 tests. The document-layout and catalog
checks and `git diff --check` pass. These tests do not execute the FPGA and do
not imply that the pending performance gate passes. No simulator numerical
model or frozen figure package is changed by this repair checkpoint.
