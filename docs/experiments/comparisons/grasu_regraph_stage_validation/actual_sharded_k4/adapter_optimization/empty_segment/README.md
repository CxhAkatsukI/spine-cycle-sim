# Empty-Segment Helper Optimization

## Finding And Scope

The production adapter can avoid the generated pipelined helper's empty-row
exit by making the segment-bound decision **before starting a non-inlined
helper**. A caller-side `continue` alone did not change RTL timing. Both
attempts, including that unsuccessful control, are retained here.

The paired results below are **C/RTL co-simulation evidence, not routed or
measured FPGA speedup**. A subsequent [production XO checkpoint](production/README.md)
passes compile and frozen-K4 ABI checks; route was not started because its
memory admission was refused. No SST timing parameter, frozen plugin, paper
or existing board result was changed. The candidate remains default-off in
its owning HLS repository.

The motivation is the [four-partition A4/K4 diagnostic](../../matched_a4/sssp_partition_round/README.md):
its frozen K4 model visits many interior empty rows, not just an empty tail.
That negative model result remains intact. Neither it nor this local RTL
improvement establishes original-A4 performance matching.

## What Changed

`GRASU_REGRAPH_SKIP_EMPTY_SEGMENT=1` selects a conditional call to
`emit_row_segments`. The existing row-prefetch and stop-after-last flags are
enabled in **both** paired arms. With the new flag off the helper is inlined;
with it on the helper is kept separate so the caller can bypass its start.

The guard compares `begin >> 4` with `(end + 15) >> 4`, after capacity
clamping. It is deliberately not `begin == end`: an unaligned empty row can
still generate masked packets under the existing ABI. Allocated all-dummy
segments, including a source-zero reservation, are still read and emitted.
No sparse-source index, new host preprocessing or free padding removal is
introduced. The kernel arguments, packing and memory interfaces are unchanged.

The candidate RTL has a guarded helper `ap_start`; the first attempt had an
unconditional helper start. Generated Verilog for both arms is archived so
this scheduling distinction can be reviewed independently of the C++ source.

## Paired RTL Results

Vitis HLS 2024.1, `xcu55c-fsvh2892-2L-e`, requested 150 MHz; weighted,
destination-sharded, shared-master adapter. Every arm checks thirteen calls
and 200 exact packets, including `data`, `keep`, `strb` and `last`.
The co-simulation memory transactor is **not** a routed HBM timing model.

| Sources / occupied position | Existing combined flags | Guard only, v1 | Explicit helper, v2 |
| --- | ---: | ---: | ---: |
| 1 / first | 349 | 349 | 349 |
| 1 / last | 280 | 280 | 280 |
| 8 / first | 297 | 297 | 297 |
| 8 / last | 826 | 826 | 310 |
| 9 / first | 297 | 297 | 297 |
| 9 / last | 976 | 976 | 388 |
| 65 / first | 297 | 297 | 297 |
| 65 / last | 5,878 | 5,878 | 1,150 |
| 1,025 / first | 297 | 297 | 297 |
| 1,025 / last | 89,878 | 89,878 | 14,230 |
| 65 / periodic | 5,822 | 5,822 | 1,844 |
| 9 / no slots | 122 | 122 | 122 |
| 0 / no slots | 39 | 39 | 39 |

First/last cases have seven segments in their occupied row; periodic cases
have three segments in every seventh row. The two single-source labels denote
identical logical placement; the table retains their observed sequential
transaction latencies rather than claiming isolated, reset-per-call timing.
The largest control improves by 6.316x; this is not a whole-accelerator ratio.
First-only cases retain their cycles because the previous optimization had
already stopped the empty tail. All thirteen v2 baseline cycle counts are
identical to v1, even after source extraction.

| HLS estimate | Existing combined flags | Explicit helper |
| --- | ---: | ---: |
| BRAM_18K | 15 | 15 |
| DSP / URAM | 0 / 0 | 0 / 0 |
| FF | 12,183 | 12,314 |
| LUT | 17,202 | 17,473 |
| Estimated clock period | 4.867 ns | 4.867 ns |

These are synthesis estimates, not routed resource/timing admission.

## Functional And Evidence Gates

The [functional package](functional/verification.json) freezes twelve C++
configurations: six legacy checks and the row-prefetch/stop-after-last
candidate with the new flag off/on in weighted, destination-only and
unit-weight formats. Each of the latter six checks passes 254 scenarios and
1,482 exact packets. Coverage includes partial row-cache blocks, capacity
truncation, unaligned `begin == end`, allocated dummy segments and a dummy
source-zero reservation before a live row.

The [final regression record](checks/verification.json) retains all 304
passing Python tests for original-ReGraph, sharded-K4, repository structure
and artifact transport. The earlier functional attempts' logs are preserved
there as supplementary history; the final functional package alone carries
the complete pre-execution source snapshot. Numerical C++ and the default
SST plugin are unchanged; the four-partition package retains its preceding
28/28 C++ regression evidence.

The [paired verification index](evidence/verification.json) links both
[v1](evidence/paired-v1.json) and [v2](evidence/paired-v2.json) reports.
Each raw archive contains the exact execution source snapshot, project
compile flags, HLS reports, generated RTL, C/RTL logs, transaction latencies,
test vectors and resource records. Compiled vendor simulator tools are not
bundled. Packaging rechecks historical snapshots, not the current worktree's
possibly newer source. It also checks the effective project flags, FPGA part,
rounded requested clock, complete packet traces and bounded execution.

Paired studies run the two arms sequentially with an eight-GiB sampled tree
budget, sixteen-GiB live host-memory reserve and 2,700-second outer timeout.
Each child additionally has an eight-GiB address-space cap and 1,200-second
timeout. The functional gate uses a three-GiB sampled tree budget and
240-second outer timeout. Sampled pidfd cleanup is not cgroup containment.

## Reproduction And Owners

HLS ownership: `grasu-regraph-integration/kernels/pma_to_regraph_adapter/`.
The [experiment owner](../../../../../../../spine_cycle_sim/experiments/sharded_k4_stages/empty_segment/README.md)
separates execution, analysis, historical validation and delivery.
From the simulator root, use fresh paths:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.study \
  --integration /home/chuxiao/grasu-regraph-integration \
  --output results/empty-segment-paired

python3 -m spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.functional \
  --integration /home/chuxiao/grasu-regraph-integration \
  --output results/empty-segment-functional \
  --destination results/empty-segment-functional-package
```

The local historic run root is
`/data/chuxiao/experiments/sharded_k4_skip_empty_segment_20261011/`.
The v1 source snapshot must be used to reproduce its negative control;
current source implements v2. `delivery --run V1 --run V2 --destination NEW`
revalidates and seals the paired controls without rerunning or retiming them.

## Remaining Acceptance

The production XO without test-only interface depths now passes ABI checks.
Route and check final timing/connectivity, then run alternating paired board
tests with complete-result and resident-boundary checks. Synchronize this new
behavior in a separate simulator candidate while replaying the legacy model
exactly. Only then redo the four-partition A4/K4 comparison under documented
resource and timing conditions. A local helper improvement does not close
the whole-system, convergence or original-publication validation goals.
