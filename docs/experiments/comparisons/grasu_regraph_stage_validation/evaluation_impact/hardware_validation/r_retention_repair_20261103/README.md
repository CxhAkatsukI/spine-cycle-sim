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
4. Retain independent G admission. The previous four AU G controls pass;
   invalidate that admission if G's implementation or boundary changes.
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
or interpreted as evidence that a kernel became faster. Independent G rows
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

The weighted-SSSP and CC generate-only packets are prepared under
`/data/chuxiao/builds/gr-directory-spans-20261103/{sssp,cc}/`. They pin the
committed repair and contain algorithm-specific adapter compile commands.
They are not compiled or routed images, and the running ResPR route does not
depend on them. Their eventual replacement must preserve each algorithm's
eleven-XO topology; the twelve-XO PageRank replacement command is not
applicable unchanged.

Each compiler job has a 40-GiB hard limit, 36-GiB high watermark, zero swap,
an atomic full-budget reservation, and a 40-GiB live-memory watchdog reserve.
The full link has a six-hour timeout. The accepted admission and resource
samples are in its execution reports. The C/RTL passes are **not** proof that
the FPGA performance gate passes.

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

## Checkpoint Verification

The focused build, replacement, retention, clock-record, packaging, candidate
smoke and repository-organization suites pass 48 tests. The document-layout and catalog
checks and `git diff --check` pass. These tests do not execute the FPGA and do
not imply that the pending performance gate passes. No simulator numerical
model or frozen figure package is changed by this repair checkpoint.
