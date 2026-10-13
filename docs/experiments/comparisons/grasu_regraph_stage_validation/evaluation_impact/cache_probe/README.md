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

## Code Review

The optional controls live under
`cpp/tests/evaluation_impact/common_g/hls/`:

| Owner | Responsibility |
| --- | --- |
| `cache_bank.hpp`, `cache_bank.cpp` | One full-depth 8192-segment URAM bank, preload, updates and acknowledged external writeback |
| `cache_lane.hpp` | Static 16-word edit wiring and an explicitly registered alternative; no dynamic 512-bit shifts |
| `cache_bank_control.cpp` | Independent sorted-array oracle, all insertion positions, full-word keys, both empty sentinels, same-row and dispersed updates |
| `cache_full.cpp` | Original 16-bank kernel behind an interface-depth wrapper, or a separate 16-bank registered candidate |
| `cache_full_control.cpp` | Complete 131072-segment state oracle, balanced traffic and same-bank conflicts |

Python ownership is
`spine_cycle_sim/experiments/evaluation_impact/common_g/cache_probe/`:
preparation freezes source and tool commands; `study.py` owns bounded execution;
`analysis.py` parses structured schedules and exact RTL transaction scope;
`delivery.py` freezes source, logs and reports, verifies hashes, and refuses to
promote component evidence to baseline admission. Focused tests exercise each
boundary without requiring Vitis.

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
