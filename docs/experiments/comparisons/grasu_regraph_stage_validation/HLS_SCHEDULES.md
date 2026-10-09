# Original-Kernel Scheduling Checkpoint

This checkpoint collects independent author-kernel HLS schedules. It does
**not** complete the G/A/A4/B performance study, implement the missing cycle
models, or establish a publication-speed match. The existing simulator
numerical code, frozen plugins, paper, and figure packages are unchanged.

Read the [plan](PLAN.md) and [source-functional controls](SOURCE_CONTROLS.md)
first. The machine-readable [schedule index](schedule_analysis.json) retains
every declared attempt, including failures. Raw logs, Tcl configurations,
XML/text reports, and resource measurements are in `raw_hls_schedules.tar.gz`.
The accompanying `schedule_verification.json` records hashes and checks.
The archive contains 52 declared attempts: 24 successful syntheses/repeats
and 28 retained failures, not 52 independent performance samples. Four fresh
source-functional controls exactly match the preceding checkpoint. All 61
focused Python tests and six existing C++ test executables pass. The 2,437
protected evidence files and frozen plugin hash are unchanged.

## What Was Checked

| Control | Configuration | Result |
| --- | --- | --- |
| G cache, DDR, binary search, dispatch | Pinned GraSU source, 16 slots/segment, U250, 200 MHz target | All four top-level kernels synthesized |
| A4 Little, 4-way merger, HBM wrapper | Pinned/generated ReGraph, 4 Little / 0 Big, U55C, 210 MHz target | All three top-level kernels synthesized |
| A components: Big, 11-way Little merger, 3-way Big merger | Pinned/generated ReGraph, 11 Little / 3 Big, U55C, 210 MHz target | All three top-level kernels synthesized |
| A4 and A PR apply | Same source and respective topology; explicit control-interface compatibility directive | Both synthesized, with a repeat check |

These are twelve distinct kernel/configuration controls, not twelve complete
accelerators. In particular, synthesizing one Little kernel with a four-Little
configuration does not synthesize or route the complete four-kernel system.
No graph traversal or temporal batch is timed by `csynth_design`.

## Scheduling Findings

| Component/loop | Achieved II | Reported pipeline depth | Interpretation |
| --- | --- | --- | --- |
| G cache `process_loop` | 3 | 7 | Do not model each PE as accepting one update every cycle |
| G cache preload/writeback outer loops | 16 | 18 | Each iteration accesses sixteen 512-bit segments |
| G DDR inner 16-stream polling loop | 1 | 146 | This is the inner loop, not complete update/search latency |
| R Little edge reader | 1 | 3 | Up to eight physical edges per issue, subject to memory and stalls |
| R Little scatter | 1 | 4 | Source-service and finite-buffer waits still matter |
| R Little gather | 1 | 6 | Eight private gather lanes, not a single shared gather array |
| R Little local drain/merge | 1 | 3 | Emits 32,768 two-vertex rows for a full 65,536-vertex partition |
| R 4-way / 11-way Little merger | 1 | 4 | Consumes two values per pipeline per merge iteration; eight iterations pack one 512-bit output |
| R PR apply, both configurations | 1 | 99 | Pipeline depth is not the initiation interval or complete kernel latency |

Depths above are the XML report's `PipelineDepth`, not independently measured
first-input-to-last-output times. Dynamic trip counts and overall kernel
latencies remain `undef`; the analysis preserves them rather than assigning
zero or deriving an unsupported whole-workload runtime. Nested trip-count
ranges are retained verbatim.

The G cache RTL starts all sixteen `process_1` instances from the same FSM
condition and waits for all of their completion signals. This confirms
parallel launch in this tool configuration despite the absence of a nested
`DATAFLOW` pragma. The raw package retains `process_cache_process_r.v` for
inspection. This observation is not a general proof of finite-buffer
liveness for every update ordering.

The interface reports show 512-bit memory ports and 16 read / 16 write
outstanding transactions under the current tool configuration. Their
`latency=64` is an HLS scheduling setting, **not** an observed DDR/HBM latency.
The commented read-outstanding setting in the author Tcl is not treated as
an active configuration. Actual bandwidth, bursts, queue contention and
controller timing still require an admitted memory model or measurement.

The Little top reports 64 URAM blocks; the Big top also reports 64. These are
component estimates, not routed full-system area. A4 has four edge-reader
ports and four source-state read/write ports, plus the PR degree port. Merely
matching the number of Little frontends does not prove that our current K4
shared downstream has equivalent buffers, gather resources or output rate.

## Tool And Platform Boundaries

The installed tool is Vitis HLS 2024.1, build 5069499. GraSU's publication used
SDAccel 2019.2. Current upstream GraSU uses sixteen 32-bit slots, whereas its
paper specifies eight. This campaign is `G-source16`, not `G-paper8`.

The requested U280 part is absent from this local installation. The initial
U280 attempts are retained as failures. Subsequent R scheduling checks
explicitly target `xcu55c-fsvh2892-2L-e`; they are **not** relabeled U280
reproductions. The 210-MHz target is the paper's normalized reference, not a
recovered Table IV graph-specific routed clock.

Two compatibility adjustments are explicit:

- A forced header supplies the old environment's global 32-bit `uint` alias
  and asserts integer widths. Author algorithm sources remain unchanged.
- Current Vitis rejects PR apply because the unstated `arg_reg` interface is
  placed in a second AXI-Lite bundle. A Tcl directive binds that scalar to
  `control`. It does not change arithmetic or add pipeline directives.

The raw attempts also preserve the initial missing `ap_utils.h` include-path
failure and the embedded-quote include-token failure. The final runner adds
the installed tool's `include/etc` directory and rejects unsupported
whitespace/quoted include paths instead of producing misleading results.

HLS warns about noncanonical/backward dataflow channels and possible deadlock
conditions. Those warnings are preserved. Successful synthesis is not C/RTL
cosimulation, a finite-stream stress test, or proof of deadlock freedom.

## Reproduction

Use the source pins and tool prerequisites from the [reading guide](README.md).
These commands use fresh output directories and retain failed rows:

```bash
python3 scripts/run_upstream_stage_synthesis.py \
  --contract configs/experiments/grasu_regraph_upstream_synthesis_u55c_v2.json \
  --tool /data/yxx/tools/xilinx/Vitis_HLS/2024.1/bin/vitis_hls \
  --out results/upstream_stage_controls/reproduce_schedules

python3 scripts/run_upstream_stage_synthesis.py \
  --contract configs/experiments/grasu_regraph_upstream_synthesis_apply_compat_v3.json \
  --tool /data/yxx/tools/xilinx/Vitis_HLS/2024.1/bin/vitis_hls \
  --out results/upstream_stage_controls/reproduce_apply_compat

python3 -m unittest tests.test_upstream_stage_synthesis
```

The twelve-row contract intentionally has no apply control-bundle directive;
its two apply failures remain part of the experiment. The two-row follow-up
declares that compatibility change separately. The U280-first contract is
also preserved; this machine cannot reproduce its R scheduling results.

For an analysis, pass run directories and their original source contracts in
matching order to `scripts/analyze_upstream_stage_synthesis.py`. The analyzer
checks original contract hashes and semantic equality of the saved snapshot,
verifies report hashes, and includes failed/unstarted rows. Earlier runners
serialized JSON snapshots; their byte hashes differ from the original input
contract. Neither identity is overwritten or falsely called equal.

## Remaining Acceptance Gates

Next implement independent G and original-R finite-resource cycle components
from these source/schedule contracts, checking state, stream conservation,
backpressure and memory completion. Restore original workload/layout and
timing-window admission before comparing any published rate. A4/B must reuse
the same downstream resource configuration and report overlap instead of
adding isolated stage times. G, adapter+R and host orchestration still need
separate accepted event windows. No timing multiplier or fitted publication
score was introduced by this checkpoint.

Primary tool references: [HLS synthesis-summary semantics](https://docs.amd.com/r/2024.1-English/ug1399-vitis-hls/Synthesis-Summary)
and [U280 device identity](https://docs.amd.com/r/en-US/ug1314-alveo-u280-reconfig-accel/UltraScale-Device).
