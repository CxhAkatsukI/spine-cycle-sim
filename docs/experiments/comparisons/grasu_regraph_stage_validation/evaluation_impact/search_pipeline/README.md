# Finite G Search Pipeline

## Decision

This is the implementation-feasibility follow-up to the
[metadata-buffer prediction controls](../metadata_credits/README.md), not a
replacement baseline or a new Spine speedup result. That model study stays
within 2% of the source-derived forwarded original on its complete declared
nonempty matrix. It does not prove that the corresponding hardware meets
200 MHz or that arbitration is free.

This checkpoint implements an isolated 64-context search path, tests ordered
results and bounded backpressure, and queues separate HLS/RTL checks. Complete
G, original-publication timing and baseline composition remain unadmitted.
Read the [overall plan](../PLAN.md) before using these results.

## Implementation Ownership

The candidate is confined to
`cpp/tests/evaluation_impact/common_g/hls/search_pipeline/`:

| File | Responsibility |
| --- | --- |
| `types.hpp` | Packed requests/responses, lane identity and eight-way selector |
| `workers.hpp` | Input distribution, ordered publication and lane credits |
| `search_worker.hpp` | Explicit request/response phases for each dependent binary-search context |
| `transport.hpp` | Two-level request arbitration, shared metadata reads and tagged response routing |
| `network.hpp` | Shared dataflow wiring, finite host execution and FIFO depths |
| `top.cpp` | Thin isolated-kernel interface declarations |
| `finite_host.hpp` | Host-only bounded stream delegates and channel conservation checks |
| `control.hpp` | Independent scalar oracle and complete ordered packet checks |
| `control.cpp` | All declared prepared inputs, dispatched over four CUs |
| `rtl_control.cpp` | Small self-contained C++14 testbench for HLS/RTL |

The runner package has one owner at
`spine_cycle_sim/experiments/evaluation_impact/common_g/search_pipeline/`.
Preparation, bounded execution, source analysis, resource admission, synthesis,
RTL analysis and delivery are separate modules. It reuses the existing bounded
runner, rather than adding a production topology flag.

The subsequent [hardware campaign](../hardware_validation/README.md) tracks
fresh RTL retries separately from the original frozen source evidence below.
The shared-network extraction replay passes all 38 inputs and eighteen
testbench-source calls; ordered output checks, probe counts and channel
conservation match its pre-extraction reference. Host blocked-write counts are
scheduling observations, not deterministic hardware cycles. New registered
gather and nonblocking feedback candidates need their own RTL and schedule
checks; neither changes the production kernel or cycle engine yet.

The subsequent host delegate yields after releasing its queue mutex on an
empty `read_nb` or `size` poll. This prevents C-simulation polling threads
from occupying their affinity cores while producers need those same cores.
`finite_host.hpp` is excluded under `__SYNTHESIS__`; this is not an HLS
latency optimization or a cycle-model change. Fresh source controls must
still check every packet, probe count and FIFO conservation result. Earlier
attempts keep their original delegates and timeouts.

There are 64 search contexts per CU, grouped eight by eight, and one shared
metadata AXI bundle for row and binary-search reads. Each context owns at most
one ordered update until its result releases the lane credit. The central
request/response FIFOs each have 32 entries; other internal FIFOs have depth
two. All 339 internal channels must conserve and drain. Their declared token
storage is 38,608 bits per CU, excluding context registers, AXI buffers,
hot cache and implementation overhead. This is not a whole-G area estimate.

Separate arbitration/FIFO stages shorten the combinational selection path in
source structure. Whether they meet the target clock and what latency they add
must be measured from HLS/RTL. At this isolated HLS checkpoint their added
latency was not incorporated into the cycle engine. Work parity below does not
justify carrying over the earlier model's 2% timing result to this HLS implementation. The subsequent
[finite cycle-model checkpoint](finite_model/README.md) adds these declared
stages behind a default-off configuration. Its explicit cycle assumptions do
not replace the pending HLS schedule measurement.

## Controls And Evidence

The complete source matrix retains all nineteen metadata-study inputs:
empty, one, three, lane boundary, cold boundary, small mixed/hot/cold,
neighbor, large, larger, same key, amortized, amortized large, same-key large,
same-key amortized, owner alias, hot amortized and cold reuse. Batch sizes range
from zero to 65,536; no failing or inconvenient input is dropped.

Each input is executed with unblocked output and with paused/periodically
stalled output, then checked separately on all four CUs. That is 38 executions
and 152 CU controls. The oracle checks every ordered 96-bit result and sideband;
all internal channels and the external bounded output must drain. Binary probe
counts must equal the corresponding M32/64-cycle model control. Matching probe
counts proves work agreement, not AXI timing calibration.

The final frozen source matrix passes all 38 executions and 152 CU checks.
Sixteen stalled-output executions observe actual blocked output writes; all
339 internal channels per CU conserve and drain. Maximum observed control
process RSS is 40,056 KiB (39.1 MiB). This is process RSS, not an aggregate
build-memory measurement or device resource estimate.

The C++14 testbench additionally covers counts 0, 1, 63, 64, 65, 127, 128, 129
and 257, each with mixed and repeated keys, for eighteen calls. Its ordinary
source execution is not RTL execution. HLS must independently pass C simulation,
synthesis, all eighteen RTL transactions and the 5-ns clock gate. External RTL
`TREADY` backpressure is not exercised by this small testbench; that remains a
separate integration requirement.

All eighteen C++14 testbench source calls also pass. This checks the testbench
and algorithm in a host executable; it does not close the RTL or clock gates.

The [evidence index](evidence/index.json) owns the complete final matrix,
preceding metadata report, HLS queue snapshot and raw capsule. The capsule
contains frozen source, all inputs, compiler/dependency identities and raw
control logs. Machine-local binaries and vendor headers are not redistributed.
Its live HLS report is indexed separately; the committed snapshot never implies
that a queued job has completed.

Retained attempts are intentional:

| Attempt | Result |
| --- | --- |
| `source-controls` | GCC vendor-header multiple definitions and missing helper linkage; no functional result |
| `source-controls-v2` | Process termination from large inherited per-thread stacks within the unchanged 2-GiB bound; no functional result |
| `source-controls-v3` | Complete 38-execution finite source matrix passed; earlier runner identity |
| `source-controls-v4` | All 38 final frozen controls and eighteen C++14 testbench source calls pass, with dependency pins |

The first failures were host harness/build failures, not measured FPGA
slowdowns. The correction uses one vendor-header translation unit, explicit
helper linkage, 1-MiB host thread stacks and two malloc arenas. The process
memory cap was not raised. Host thread scheduling and wall time are never
reported as device cycles. The vendor GCC packet type exposes sixteen keep
bits for this 96-bit packet; this host quirk is logged explicitly, not used to
claim a sixteen-byte RTL payload. RTL interface/sideband behavior still needs
its own check.

## Regression Verification

The focused regression passes all 76 tests across the search pipeline, its
preceding G controls and repository structure. Its saved
[resource record](verification/focused-tests-v2.resources.json) and
[test log](verification/focused-tests-v2.stderr.txt) record a 2-GiB hard cap,
8-GiB reserve, CPU affinity 126/127 and peak process RSS of 65,336 KiB.
The [verification index](verification/index.json) pins the copied logs.

The preceding regression attempt is retained too: 75 tests passed and the
capsule test failed because packaging had not yet created `evidence/index.json`.
The completed capsule was then checked by the same suite; no numerical code
change or relaxed assertion was used to obtain the pass. Core/SST numerical
code is unchanged and its earlier regression results are not claimed as fresh
tests in this checkpoint.

## Memory-Admitted HLS

The isolated HLS job has an 8-GiB hard cap, 7-GiB high watermark, no swap,
CPU 127, a 1,800-second tool timeout and a 24-GiB system reserve. Independent
tools need not exit when their full declared budgets fit. An active cache
comparison reserves 6 GiB and a pending/active route reserves 40 GiB. The
optional `--background-memory-gib` reserves concurrent non-FPGA work; the
current R study needs 6 GiB. With cache finished and route plus R active,
admission requires 78 GiB available (8 + 24 + 40 + 6). If cache is also active,
it requires 84 GiB. Unknown state, unbounded or oversized competing limits
fail closed. Waiting for memory is bounded to twelve hours by default.

The lightweight supervisor is separately capped at 512 MiB. Waiting is not
synthesis progress, and expiry/failure must be retained. The original cache
and routing thresholds are not reduced, other users' processes are untouched,
and no system cache is dropped. Source controls use a 2-GiB cap, 8-GiB reserve
and 600-second per-case timeout.

## Reproduction

Use fresh paths. The basis is the completed metadata-buffer study, including
its inputs and `results.json`, not a figure spreadsheet.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.study \
  --output /path/to/fresh-source-controls \
  --basis /path/to/g-metadata-credits-v1/matrix \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis \
  --output /path/to/fresh-hls-attempt --basis /path/to/fresh-source-controls \
  --previous-unit spine-grasu-full-cache-20261013-v3.service \
  --route-unit spine-sharded-k4-bank-sssp-20261012-v2.service \
  --background-memory-gib 6 \
  --maximum-wait 43200

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.delivery \
  --output /path/to/fresh-evidence --matrix /path/to/fresh-source-controls \
  --hls /path/to/fresh-hls-attempt --freeze /path/to/pre-edit-sources.tar.gz \
  --retained /path/to/retained-source-attempt

python3 -m unittest tests.test_grasu_search_pipeline -v
```

Raw attempts reside under
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-search-pipeline-v1/`.
The source code is optional test HLS, not linked into CMake core or the SST
plugin. Core/SST numerical code is unchanged this checkpoint. Earlier core/SST
regressions remain historical evidence, not newly rerun calibration.

## Production Wrapper RTL And ABI

The separate `common_g/search_binding/` package checks the actual compact-host
argument shape. Its source matrix has 216 calls, covering pointer aliases,
unused-pointer poisoning, two metadata generations and stalled consumers. This
does not prove that exported registers or RTL have the same interface.

| Module | Responsibility |
| --- | --- |
| `rtl_preparation.py` | Require complete source controls, freeze source/runner/reference ABI, produce vendor Tcl |
| `rtl.py` | Thin CLI, bounded memory admission, execution and final report |
| `rtl_analysis.py` | Keep C simulation, RTL, clock and ABI decisions separate; retain partial reports |
| `abi.py` | Structured comparison of exported kernel arguments, control registers and AXIS signals |
| `rtl_review.py` | Read-only reanalysis of a retained ABI-only failure, preserving every non-ABI observation |
| `hls/search_binding/rtl_control.cpp` | Eighteen real-wrapper calls, including metadata replacement at unchanged pointer addresses |

Preparation requires successful, hash-checked binding and isolated source
controls using identical shared search sources. It also replays their analyses;
a status label alone is insufficient. The reference is the routed search
solution's `impl/kernel/kernel.xml` and `impl/ip/component.xml`, not a handwritten
assumption about argument offsets. Exported XO metadata must preserve all eleven
arguments, unused-pointer qualifiers, control-register offsets, `ap_ctrl_chain`
and the 96-bit AXIS payload with 12-bit keep/strb sidebands.

The RTL bench covers the same nine count boundaries, each with two metadata
generations, using the actual aliased host pointers. C simulation, all eighteen
RTL transactions, exported ABI and the 5-ns estimate are independent gates. A
functional/ABI pass with a slower estimate is explicitly a clock-gate failure.
External RTL `TREADY` stalls, integrated G, routed timing and board execution
remain untested by this component probe. Its results never admit publication
performance or replace a whole-G validation.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding.rtl \
  --output /path/to/fresh-wrapper-rtl \
  --binding /path/to/completed-binding-controls \
  --search /path/to/completed-isolated-source-controls \
  --reference /path/to/routed-bin-search/solution \
  --previous-unit spine-grasu-full-cache-20261015-v1.service \
  --route-unit spine-sharded-k4-bank-sssp-20261015-v1.service \
  --background-memory-gib 40 --maximum-wait 3600
```

The wrapper tool uses an 8-GiB hard / 7-GiB high bound, no swap, CPU 124 and
a 1,800-second timeout. With cache finished, routing active and 40 GiB reserved
for other work, admission requires 112 GiB available (8 + 24 + 40 + 40).
It does not wait for other tools to exit when this full budget fits.

The fresh hardware campaign's actual wrapper completed all eighteen RTL
transactions with a 3.650-ns synthesis estimate. The original analyzer failed
because Vivado also packages a scratch `kernel.xml`. Its original failure
remains intact. A separate hash-checked review of the same raw reports and XO
uses the unique canonical exported ABI and passes all ABI checks against the
routed reference: eleven arguments, 23 registers and the declared AXIS signals.
No simulation was rerun or timing observation changed by the review.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding.rtl_review \
  --output /path/to/fresh-independent-review \
  --attempt /path/to/terminal-ABI-only-failed-wrapper-attempt

python3 -m unittest tests.test_grasu_search_binding_rtl \
  tests.test_grasu_search_binding_review
```

The reviewer accepts only a successful, non-timeout tool execution with
passing C simulation/RTL and an ABI-only analysis error. Changed original
sources, frozen runners, reports, XO or non-ABI observations fail closed.
Canonical-XO parser tests cover scratch metadata, missing exports and
ambiguous IP components. This component pass still does not establish
external RTL backpressure, complete-G correctness, routed timing, board
performance or publication matching.

## Remaining Integration Gates

First inspect actual search schedules, resource usage and clock, keeping RTL
correctness separate from clock feasibility. Combine admitted search with the
complete cache/cold paths, local-destination weighted ABI and actual finite
interfaces; check full-G resources, hazards, backpressure and completion. Update
the explicit model for the real schedule, then rerun fresh core/SST regressions
and the entire common-input timing matrix. Do not promote an isolated pass.

Publication timing, neighboring R workloads, actual G-to-adapter/R temporal
handoff and host windows still need independent evidence. Only an admitted
baseline can support the new warm-to-warm Spine demo and Figure 7--11 impact
analysis. No paper, frozen figure package, production plugin or bitstream is
changed here.
