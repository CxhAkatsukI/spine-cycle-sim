# Real Host-Prepared G Source Check

## Decision

`g-real-prepared-source-v5` passes all 42 declared rows:
`REAL_HOST_PREPARED_G_SOURCE_PASS_NOT_RTL_OR_BOARD`.
The unchanged production host builder, runtime plan and packing feed complete
G source execution and the actual bank-streaming adapter. This closes a
functional input/handoff gap, **not** integrated RTL, FPGA performance,
original-paper reproduction or admission of a new baseline.

The [real-input evidence index](evidence/index.json) packages v1, v4 and v5,
including their frozen sources, contracts, dependency identities, raw logs,
analysis and resource observations. The [regression index](regression_evidence/index.json)
packages synthetic v7, v9 and v10; the earlier v6 capsule remains unchanged in
the [shared-core index](../shared_core_evidence/index.json).

## Declared Matrix

| Inputs | Vertices | Initial edges | Physical updates | Partition size |
| --- | --- | --- | --- | --- |
| AU mixed / weight change | 3,409 | 8,192 | 512 / 8,192 | 65,536 |
| SU mixed / weight change | 3,224 | 8,192 | 512 / 8,192 | 65,536 |
| WK mixed / weight change | 5,930 | 8,192 | 512 / 8,192 | 65,536 |
| AU mixed partition smoke | 3,409 | 8,192 | 512 | 1,024; functional only |

Each case runs the pristine-cache and registered-cache arms, with an empty
batch followed by two resident half-batches. This gives 42 aggregate rows,
60 physical shard executions/handoffs and 53,248 physical mutations across
the complete matrix. A weight change is a deletion followed by insertion;
4,096 logical weight changes therefore require 8,192 physical updates.
The 1,024-vertex partition check exercises four shards, but is not evidence
for native multi-partition hardware capacity or performance.

These are compact file-order real-topology slices with derived mixed and
weight-change operations, not full graphs or recovered timestamp-ordered
traces. The production preparation reserves future positive variants and
keeps mapping/layout fixed across batches. All edited segments in these real
cases are hot; cold updates remain covered by the separate synthetic matrix.

## Checks And Limits

- Check host ID permutation, physical update encoding/order and local dst19.
- Use the unchanged lane-aware 23-channel host plan and packed PMA buffers.
- Run four finite-FIFO search CUs, production dispatch, both full-capacity
  131,072-segment hot halves and production cold-DDR functions.
- Compare every physical PMA segment, including unused padding, after each
  batch against an independent mutation oracle; check metadata stays fixed.
- Feed these resulting PMAs directly into the actual adapter. Verify finite
  output-FIFO conservation, packet sidebands and the complete weighted edge
  set after translating back to external IDs. No compact replacement input
  is constructed for this handoff.
- Require exact known pristine-cache vendor diagnostic counts, no unknown
  runtime messages, clean compilation, and pinned vendor dependencies.

Internal cache/DDR C-simulation FIFOs remain unbounded. This is not a test of
OpenCL/XRT binding, integrated RTL/backpressure, board timing, ReGraph
computation or host-inclusive throughput. C-simulation wall time is not a
device cycle measurement. Both cache arms share the current search core;
this is not a speed comparison against the original GraSU publication.

## Regression And Failures

Synthetic `g-complete-source-v10` passes all twelve original composition rows.
Its stdout is byte-identical to v6, all parsed row counters match, and the
classified vendor diagnostics match; [the equivalence record](regression_equivalence.json)
pins both reports and stdout identities. The harness now waits for its two
external cache-consumer threads before snapshotting FIFO conservation;
search/cache/DDR HLS logic and capacities are unchanged by this harness fix.

| Attempt | Retained outcome |
| --- | --- |
| Real v1 | Compiler vendor-header warnings rejected before execution; later attempts classify those includes as system headers while keeping dependency pins |
| Real v2/v3 | Wrong upstream path; preparation only, partial trees and systemd journals retained; no result capsule or executed matrix |
| Real v4 | First six rows were functionally correct, but the analyzer expected twice the actual hot-insertion diagnostic count; failed report unchanged |
| Real v5 | Complete 42-row source-only pass |
| Synthetic v7 | Memory admission refused a 120-GiB reserve; no compiler launch |
| Synthetic v8 | Wrong upstream path during preparation; no result capsule or execution |
| Synthetic v9 | FIFO-conservation snapshot raced the external cache consumer; failed run retained |
| Synthetic v10 | Corrected join barrier; complete twelve-row regression pass |

Raw attempts live under
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.
Preparation-only failures have no `results.json`; they are not represented
as executed rows in either portable index.

## Reproduce And Verify

From the repository root:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.host_prepared.study --help
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.host_prepared.delivery --help
python3 -m unittest tests.test_grasu_host_prepared tests.test_grasu_complete_pipeline -v
```

Use a fresh output path, the pristine `GraSU_kernels/src` directory as
`--upstream`, production G+R as `--integration`, and vendor `--hls-include`.
The source-only runner uses C++20/O1 with assertions, a 4-GiB hard/3-GiB high
memory cgroup, no swap, CPUs 124--125, a 104-GiB available-memory reserve and
900-second per-step timeouts. Bound the supervising service as well.
Synthetic verification still defaults to a 120-GiB reserve; the explicit
`--reserve-gib 104` option used by v10 preserves room for two bounded
40-GiB routes plus 24 GiB of background/system reserve. Values outside
104--120 GiB are rejected. FPGA admission separately reserves full cgroup
budgets atomically; other tools need not exit if the budgets fit.

The passing real-input compiler peak RSS was about 548 MiB; matrix execution
peaked near 238 MiB. These are host verification resources, not FPGA area or
accelerator throughput. Next gates remain complete G backpressure/state and
real XRT bindings, routed timing, board handoff/continuous batches, isolated
G/R controls and the new Spine performance matrix.

The focused regression suite passes all 212 tests, including the ten new
host-prepared/packaging tests and fifteen repository-structure tests. It ran
with a 2-GiB physical memory limit and sampled about 90 MiB peak process-tree
RSS. Raw logs and the resource record are retained at
`verification-host-prepared-v2/` under the campaign root. The v1 launcher
rejected an incorrect API keyword before starting any test subprocess; its
launch-error record is retained separately.
