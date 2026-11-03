# R Hardware Retention Repair

## Acceptance Order

This study continues the failed [source-retention control](../source_performance_retention_20261103/README.md).
It does not promote that control, change the paper, or overwrite frozen figure
packages. Simulator near-parity is not FPGA performance admission.

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
relink manifests are `route-{sssp,cc}-v1/manifest.json` under that build root.
They retain all ten other XOs and the frozen connectivity and have not been
executed. The active ResPR link still has priority for full-link memory.
These are component results only: the existing measured four-Little R
control uses PageRank arithmetic and cannot admit the weighted-SSSP or CC
resident R path.

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
The C simulation, gather synthesis and host compile are complete; the
tail candidate has not been linked into a full image or board tested.

### Timeout Recovery

The preceding production ResPR link took 5 h 49 min even with a seeded
IP cache. The active repair link still uses its original six-hour deadline.
If it ends specifically with a logged watchdog timeout and verified worker
cleanup, prepare a separate attempt with the same link command (except output
paths) and a twelve-hour deadline:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.cached_retry \
  --previous /data/chuxiao/builds/gr-directory-spans-20261103/route-respr-v1 \
  --output /data/chuxiao/builds/gr-directory-spans-20261103/route-respr-cached-v2 \
  --unit gr-directory-spans-route-20261104.service \
  --invocation 84845edf6b294efb8f856df572d2a341
```

Execute with the same module's `--output ... --execute` inside a fresh service
with the same 40/36-GiB hard/high limits and zero swap, and a service runtime
above twelve hours. Full memory admission and the live-memory watchdog remain
unchanged. Cache entries are independently copied and hashed before execution;
Vivado still selects entries using its own fingerprints. A successful original
attempt, an active build, a memory stop, or an unexplained failure does not
qualify for this retry. Point the R screen to the retry's own invocation and
start it after the retry enters its final six hours; the screen still admits
at most one measurement per control arm.

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
