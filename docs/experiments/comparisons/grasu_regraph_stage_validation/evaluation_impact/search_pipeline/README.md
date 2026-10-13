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
| `workers.hpp` | Input distribution, dependent binary searches, ordered publication and lane credits |
| `transport.hpp` | Two-level request arbitration, shared metadata reads and tagged response routing |
| `top.cpp` | Explicit dataflow wiring, interface declarations and FIFO depths |
| `finite_host.hpp` | Host-only bounded stream delegates and channel conservation checks |
| `control.hpp` | Independent scalar oracle and complete ordered packet checks |
| `control.cpp` | All declared prepared inputs, dispatched over four CUs |
| `rtl_control.cpp` | Small self-contained C++14 testbench for HLS/RTL |

The runner package has one owner at
`spine_cycle_sim/experiments/evaluation_impact/common_g/search_pipeline/`.
Preparation, bounded execution, source analysis, resource admission, synthesis,
RTL analysis and delivery are separate modules. It reuses the existing bounded
runner, rather than adding a production topology flag.

There are 64 search contexts per CU, grouped eight by eight, and one shared
metadata AXI bundle for row and binary-search reads. Each context owns at most
one ordered update until its result releases the lane credit. The central
request/response FIFOs each have 32 entries; other internal FIFOs have depth
two. All 339 internal channels must conserve and drain. Their declared token
storage is 38,608 bits per CU, excluding context registers, AXI buffers,
hot cache and implementation overhead. This is not a whole-G area estimate.

Separate arbitration/FIFO stages shorten the combinational selection path in
source structure. Whether they meet the target clock and what latency they add
must be measured from HLS/RTL. **Their added latency is not yet incorporated
into the cycle engine.** Work parity below does not justify carrying over the
earlier model's 2% timing result to this HLS implementation.

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

## Safe HLS Queue

The isolated HLS job waits for the previously queued complete-cache comparison
to terminate. It has an 8-GiB hard cap, 7-GiB high watermark, no swap, CPU 127,
a 1,800-second tool timeout and a 24-GiB system reserve. While the pre-existing
route job remains pending/active, its full 40-GiB cgroup budget is reserved too:
admission requires 72 GiB available, rather than racing both jobs for memory.
Once that route is terminal, the threshold is 32 GiB. Waiting is bounded to
twelve hours. Unknown competing-unit state fails closed.

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

## Remaining Work

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
