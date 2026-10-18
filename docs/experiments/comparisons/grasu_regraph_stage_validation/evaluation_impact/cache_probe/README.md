# GraSU Hot-Cache HLS And RTL Controls

## Scope

This study checks whether the original GraSU cached update path and a lower-LUT
candidate have plausible HLS schedules and preserve complete cache state. It
does not change the production G HLS, core simulator, SST plugin, paper or
frozen figure handoff. It is a prerequisite for a possible cached G candidate,
not a passing whole-G performance or original-publication reproduction result.

Read the [baseline plan](../PLAN.md) for the remaining admission order and
the [hot-owner study](../hot_lanes/README.md) for the current direct-HBM
candidate's failed performance gate. Adding parallel direct-HBM owners did not
eliminate the cost of repeated read/modify/write to the same segment; a real
cache must be investigated rather than assumed in the simulator.

The earlier attempt decisions below describe their frozen checkpoints.
The [current hardware campaign](../hardware_validation/README.md) records the
subsequent paired full-cache pass and complete-G source controls. The production
wrapper check below passes its component gates, not a replacement for integrated RTL or
board measurements.

## Code Review

The optional controls live under
`cpp/tests/evaluation_impact/common_g/hls/`:

| Owner | Responsibility |
| --- | --- |
| `cache_bank.hpp`, `cache_bank.cpp` | One full-depth 8192-segment URAM bank, preload, updates and acknowledged external writeback |
| `cache_lane.hpp` | Static 16-word edit wiring and an explicitly registered alternative; no dynamic 512-bit shifts |
| `cache_bank_control.cpp` | Independent sorted-array oracle, all insertion positions, full-word keys, both empty sentinels, same-row and dispersed updates |
| `cache_pipeline.hpp` | Shared registered 16-bank cache core, full preload/writeback and depth-two internal FIFOs |
| `cache_full.cpp` | Original 16-bank kernel behind an interface-depth wrapper, or the shared registered core |
| `cache_full_control.cpp` | Complete 131072-segment state oracle, balanced traffic and same-bank conflicts |
| `cache_binding.cpp` | Production-shaped three-argument cache top, including completion-token output |

Python ownership is
`spine_cycle_sim/experiments/evaluation_impact/common_g/cache_probe/`:
preparation freezes source and tool commands; `study.py` owns bounded execution;
`analysis.py` parses structured schedules and exact RTL transaction scope;
`delivery.py` freezes source, logs and reports, verifies hashes, and refuses to
promote component evidence to baseline admission. Focused tests exercise each
boundary without requiring Vitis.

Production-wrapper ownership stays in the same package: `binding_preparation.py`
freezes inputs and checks the passing composition source identity;
`binding.py` owns memory-admitted execution; `binding_abi.py` checks registers
and both AXIS buses; `binding_analysis.py` keeps state, RTL, ABI and estimated
clock gates separate.

## Same-Stimulus Simulator Service Control

The optional CMake target `grasu_cache_timing_control` uses the existing
`CachedProcessor`, without changing model parameters, production numerical
code or the SST plugin. It reproduces the six current production-wrapper
RTL stimuli: 0, 16, 64, 4096 and 65536 balanced updates, then 4096 alternating
insert/delete operations on the same bank and row. Every call checks the
entire 131072-segment state, exactly 8 MiB preload and 8 MiB acknowledged
writeback, input drain and the same observations after reversed scheduler
registration. The external input FIFO and internal bank FIFOs are finite.

The committed [raw control and analysis](timing_control/results.json) retain
the [model output](timing_control/model.json),
[RTL transaction report](timing_control/rtl.transaction.rpt) and
[execution/source identity](timing_control/execution.json). The RTL report
is from `g-cache-comparison-rtl-v1/cache-token`, not the earlier wrapper
checkpoint with slightly different control alignment.

| Comparison | Simulator, cycles/update | RTL, cycles/update |
| --- | ---: | ---: |
| Balanced increment from 4096 to 65536 updates | 1.000000 | 1.000000 |
| Extra same-bank cost at 4096 updates, relative to balanced | 2.006836 | 2.005371 |

These are **service-increment checks, not total-time calibration**. The model
uses a `MockMemoryBackend`; its AXI preload/writeback takes different time
from the XSim memory model. For example, the empty call is 527062 model
cycles versus 278737 RTL cycles. The model also closes input after the last
committed packet, whereas the RTL bench supplies an end token. Those
differences are not removed by fitting an offset. The model clock is 200 MHz;
this production RTL probe targets 150 MHz. Only cycle increments are compared,
not equal-frequency performance or measured hardware time. No integrated-G,
FPGA timing, original-publication match or final-figure admission follows.

The successful raw attempt is
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-cache-model-timing-v2`.
It freezes the C++ tree from base commit `e4f8e18` plus the new test target,
uses GCC 15.2.0, Release `-O3 -DNDEBUG`, and separately runs the existing
`grasu_cached_processor_tests` regression. All four configure/build/run steps
exit zero. Its 2-GiB hard cgroup, 1536-MiB high threshold, zero swap and
32-GiB system reserve stay enforced; cgroup peak is 443.3 MiB, with no OOM.
This is not a host-wall-time benchmark. The retained v1 attempt failed before
compilation because the shared `/tmp` was full. V2 uses its own campaign
`TMPDIR`; neither the failed attempt nor shared temporary files were removed.

Reproduce in a fresh build/output directory, with memory admission and a
campaign-specific `TMPDIR`:

```bash
cmake -S . -B /campaign/fresh-cache-build -DCMAKE_BUILD_TYPE=Release
cmake --build /campaign/fresh-cache-build --target grasu_cache_timing_control grasu_cached_processor_tests -j1
/campaign/fresh-cache-build/cpp/grasu_cache_timing_control
/campaign/fresh-cache-build/cpp/grasu_cached_processor_tests
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.timing_analysis \
  --model /campaign/saved-model-stdout.json \
  --rtl-report docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/cache_probe/timing_control/rtl.transaction.rpt \
  --output /campaign/fresh-cache-analysis
python3 -m unittest tests.test_grasu_cache_timing
```

Save the control's stdout as the model input using the campaign runner. The
analysis hashes both inputs and refuses missing cases, changed stimuli,
incomplete traffic or invalid phase ordering. The committed-data regression
recomputes the analysis without external tools or raw campaign paths.

## Production Wrapper Gate

The completed `g-cache-binding-rtl-v1` runs the shared registered core through
the real `process_cache(pma_cache, update_stream, completion_token)` interface.
The code is the same core used in `g-complete-source-v6`, which passes all
twelve full-capacity composition rows after the behavior-preserving extraction.
Both the raw source-control attempt and its portable archive are owned by the
[complete-G guide](../hardware_validation/complete_pipeline/README.md).

This wrapper gate checks six full-state calls (0, 16, 64, 4096, 65536 balanced
updates and 4096 single-bank conflicts), input drain, exactly one completion
token with the correct payload/sidebands, Verilog transactions and XO export.
Exported arguments, register offsets, control protocol and both AXIS buses
must match the existing routed cache ABI. A synthesis estimate above 5 ns is
reported separately even if RTL and ABI checks pass. External RTL producer
stalls and whole-G composition are not covered by these six calls.

All six state/RTL calls and the exported ABI pass, with tool exit code zero.
The estimate is 3.650 ns, 87,695 LUTs, 60,274 FFs, 30 BRAMs and 256 URAMs.
RTL latencies are 278743, 278734, 278782, 282814, 344254 and 291034 cycles in
the declared call order. Full preload/writeback and one checked completion
token remain included. The exported XO SHA-256 is
`caeb04635bc0eea9d36a04ebafb576d5b31ceb608b78f89acd206f218bfec9d8`.
The [portable wrapper evidence](../hardware_validation/cache_binding_evidence/index.json)
contains frozen source/runner, reference ABI, raw reports, logs and XO.

The old routed cache used `GRASU_PURE_PIPELINE_DIRECT_CACHE`, a direct-HBM path.
The new candidate instead retains the original full hot-half capacity in URAM.
An identical host ABI therefore does **not** establish identical resources,
timing, or behavior under whole-system backpressure. Two cache halves require
512 URAMs; complete resource fit and routing remain mandatory.

Reproduce from the worktree root with fresh output paths and frozen source
controls:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.binding \
  --output /path/to/fresh-cache-binding \
  --basis /path/to/g-complete-source-v6 \
  --production /path/to/production/GraSU_kernels/src \
  --reference /path/to/routed/process_cache/solution \
  --previous-unit <bounded-predecessor.service> \
  --route-unit <bounded-route.service> \
  --maximum-wait 3600
python3 -m unittest tests.test_grasu_cache_binding
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.binding_delivery \
  --output /path/to/fresh-cache-binding-evidence \
  --attempt /path/to/completed-cache-binding
```

The HLS scope has an 8-GiB hard limit, 7-GiB memory-high threshold, no swap,
CPU 125 and an 1800-second timeout. Its supervisor has a separate 512-MiB
limit and bounded lifetime. Admission reserves 24 GiB for the system plus
the full finite budgets of the declared concurrent tools. At this launch the
40-GiB route was active and approximately 134 GiB was available, exceeding
the 72-GiB admission threshold. It started immediately; it did not wait for
other FPGA tools to terminate. The completed tool execution took 329.3 seconds
and recorded 885,460 KiB maximum single-process RSS; that RSS is not a summed
process-tree peak. The hard cgroup bound applies to the complete tool scope.

## Fixed Controls

- Unchanged author `kernel_process_cache.cpp` and `kernel_config.h` are copied
  from the pinned publication source checkout. The full original kernel body
  and directives remain unchanged; its test top supplies the external array
  depth required by RTL cosimulation.
- Vitis HLS 2024.1, U55C `xcu55c-fsvh2892-2L-e`, target 5 ns. C simulation,
  synthesis and Verilog/XSim cosimulation must all finish before analysis.
- A cache segment is 512 bits / sixteen full 32-bit words. One bank contains
  8192 segments; the complete original hot half contains sixteen banks and
  131072 segments. A full G design has two such halves.
- Single-bank calls: 0, 40 position/key operations, 64/256/1024 same-row updates,
  and 1024 dispersed updates. Every call checks every bank word and input drain.
- Extended full-cache calls: 0, 16, 64, 4096/65536 balanced updates across all
  sixteen banks, and 4096 updates to one bank/row. Every call checks all
  131072 x 16 words. Earlier two-call full-cache evidence remains separately
  identified; it is not relabeled as the extended scope.
- Full-cache candidate FIFO depth is two, with no cosimulation FIFO-depth
  inflation. Estimated clock feasibility and functional/finite-FIFO correctness
  have independent gates.

## Findings

The original single-bank RTL processes successive same-row updates at a
three-cycle incremental interval. Static unregistered lane wiring improves
that interval to two cycles, but its 6.804-ns estimate misses the 5-ns target.
The registered alternative restores the three-cycle interval and meets the
isolated 5-ns synthesis estimate while using fewer LUTs. None of these estimates
is placed-and-routed timing or an FPGA measurement.

| Isolated bank | Estimated clock, ns | LUT | FF | URAM | Same-row incremental cycles/update |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original | 3.650 | 17174 | 8878 | 16 | 3 |
| Unregistered static lanes | 6.804 | 8386 | 5613 | 16 | 2 |
| Registered static lanes | 3.650 | 8930 | 7682 | 16 | 3 |

All three use 30 BRAMs in this isolated wrapper. The lower-LUT candidate is
not faster than original at the admitted isolated clock; its purpose here is
to investigate a feasible cached path, not to claim a free update speedup.

The original complete kernel also passes full-depth C/RTL state checks,
including finite depth-two FIFOs. Vitis schedules the sixteen unrolled bank
calls concurrently even though the author helper does not explicitly use an
inner DATAFLOW directive. Treating this source as necessarily serial or
deadlocked would be incorrect. Extended original results are:

| Updates / pattern | RTL latency, cycles |
| --- | ---: |
| 0 | 278737 |
| 16 balanced | 278734 |
| 64 balanced | 278782 |
| 4096 balanced | 282814 |
| 65536 balanced | 344254 |
| 4096 single bank / same row | 291028 |

The three-cycle empty/16-update difference is control alignment, not a negative
per-update cost. The balanced 4096-to-65536 incremental interval is one cycle
per input; single-bank steady update service remains three cycles. Complete
preload/writeback dominates small batches and must not be omitted in a G
comparison.

The first extended comparison retained the original pass, but refused to
launch the registered arm when available memory dropped below the fixed
6-GiB tool limit plus 24-GiB reserve. This is a resource admission failure,
not a failed functional comparison. The subsequent attempt records bounded
memory waiting before each arm; it never lowers the reserve to force launch.
Both waits expired after 600 seconds without launching a tool. The registered
full-cache candidate and the extracted bank-helper regression therefore remain
unrun; there is no full-cache candidate timing result to compare to original.

A fresh `g-cache-full-comparison-v3` freezes the current helper and queues the
same two complete-cache arms with a 12-hour prelaunch wait **per arm**. At launch
it is `WAITING_FOR_MEMORY`, not a passing or completed attempt. The tool limit,
system reserve, clock, workloads and analysis gates are unchanged. Frozen
source is rechecked immediately before a tool may start; active/waiting reports
cannot be packaged as final evidence. This live attempt is outside the frozen
eight-attempt evidence capsule and must be packaged separately after completion.

## Evidence And Version Boundaries

The [evidence index](evidence/index.json) identifies each retained attempt and
its source, commands, C/RTL reports and failure logs. Archives are deliberately
small: generated RTL and simulator binaries remain in the raw attempt folder,
while the inputs and reports needed to reproduce or inspect a claim are
included. Failed attempts are retained alongside passes, not overwritten.

| Attempt | Outcome |
| --- | --- |
| `g-cache-bank-v1` | Tool/thread resource failure before RTL evidence |
| `g-cache-bank-v2` | C/synthesis pass; missing external-array cosimulation depth |
| `g-cache-bank-v3` | Two bank arms pass C/RTL; static-lane clock gate fails |
| `g-cache-bank-v4` | All three bank arms pass C/RTL; only original and registered meet the estimated clock |
| `g-cache-full-original-v1` | Missing external-array cosimulation depth; not evidence of a deadlock |
| `g-cache-full-original-v2` | Unchanged original full cache passes its earlier two-call scope |
| `g-cache-full-comparison-v1` | Original extended six-call scope passes; registered arm not launched due to memory admission |
| `g-cache-full-comparison-v2` | Both arms not launched after bounded low-memory waits |

The bank-v4 synthesis/RTL numbers above belong to its frozen sources. The
reviewable working source subsequently extracts the candidate helper into
`cache_lane.hpp` for the full-cache comparison. It has not yet completed a new
single-bank synthesis/RTL regression; the earlier numbers must not be assigned
to that new source identity. No production numerical code has changed.

Verify the committed archives without extracting or requiring the raw paths:

```bash
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/cache_probe/evidence"))'
```

## Important Unclosed Gaps

1. The full-G search path, weighted local-destination ABI, cold DDR path,
   cache-half selection and cache writeback-to-adapter handoff are not covered
   by this isolated cache study. Full-word sorting is not automatically the
   correct comparison order for every weighted packed format.
2. The existing independent original-G finite model uses a conservative
   pending-row hazard: it waits for update commit before a repeated row is
   accepted. These probes show the author cache RTL can sustain three-cycle
   same-row service. Its prior predicted timings must not be retroactively
   called exact RTL calibration. Any model correction needs a separate frozen
   default-regression control and explicit evidence-backed configuration.
   Correcting an overconservative original reference makes the retention
   target harder, not easier; the earlier current-G failures remain failures.
3. The original full hot half uses 256 URAMs; two halves require 512 before
   ReGraph and other storage. A logical fit in the U55C's 960 URAMs does not
   establish whole-design placement, memory-port feasibility or routed timing.
4. The preceding isolated parallel-search candidates still miss the 5-ns
   estimated target. A successful cache probe cannot close that gap.
5. No current-vs-original whole-G speedup, original-publication match or new
   Spine evaluation follows from this checkpoint. The overall goal remains
   open until the implementation, model, full matrices and composition pass.

The next cache implementation decision therefore requires four separate
checks: rerun the extracted single-bank helper; finish the registered full
cache comparison; validate weighted packed-key search/edit against the actual
host PMA layout; and integrate search, both cache halves, cold updates and
acknowledged writeback under a complete resource ledger. Only then should a
new simulator component and complete common-input matrix be admitted. A
3.650-ns isolated estimate is not evidence that this integrated path closes.

## Reproduction And Safety

From the simulator worktree root, use unique output paths:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.study \
  --output /path/to/fresh-bank-output \
  --upstream build/publication_sources/grasu/GraSU/GraSU_kernels/src

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.study \
  --output /path/to/fresh-full-output \
  --upstream build/publication_sources/grasu/GraSU/GraSU_kernels/src \
  --full-comparison

python3 -m unittest tests.test_grasu_cache_probe tests.test_grasu_cache_probe_delivery -v
```

Arms run sequentially on CPU 127 with a 900-second tool timeout, a whole-scope
6-GiB hard memory cap, 5-GiB memory-high threshold, no swap, and a 24-GiB system
reserve. Prelaunch waiting is bounded at 600 seconds and records available
memory samples; the subprocess launcher checks the reserve again. Other users'
processes and caches are untouched. `wait4` RSS is the maximum observed process
RSS, not simultaneous process-tree memory; the cgroup supplies the tree cap.

The independently queued ReGraph route keeps its original source pins and
64-GiB admission requirement. These probes neither start a second route nor
replace a measured bitstream.

For a long-wait queue, explicitly add `--memory-wait-seconds 43200`. This changes
only the maximum wait before each tool, never its memory admission threshold.
The current systemd user service is `spine-grasu-full-cache-20261013-v3`; its
supervisor has a 512-MiB cap and 26-hour lifetime. HLS runs, if admitted, enter
separate 6-GiB scopes. Inspect the live status without treating it as a result:

```bash
systemctl --user status spine-grasu-full-cache-20261013-v3 --no-pager
python3 -m json.tool /data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-cache-full-comparison-v3/results.json
```

Checkpoint verification: 61 focused Python tests pass, including committed
archive verification and the existing G/R diagnostic controls. Documentation
layout, generated catalogs and whitespace checks pass. Core/SST numerical
sources are unchanged; no new core/SST rebuild or whole-G hardware result is
claimed by this component-test checkpoint.
