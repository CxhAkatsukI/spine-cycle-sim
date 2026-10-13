# Complete Prepared-Shard G Timing Diagnostic

## Question And Boundary

Does the finite-search, complete-cache G candidate retain original G's
predicted update performance after paying for every updated destination
shard, including the actual runtime channel mapping?

This extends the [single-window study](../search_pipeline/finite_model/README.md)
and [physical cached handoff](../composition/cached/README.md). It is not
published GraSU performance reproduction, measured FPGA timing, or complete
baseline admission. The candidate remains explicit and default-off. No
production model coefficient, profile, paper, or frozen figure is changed.

All arms start with the same prepared resident PMA and exact physical update
records. Timing runs through acknowledged final writes, with complete cache
preload and writeback **once per updated shard**. Empty input skips launch.
Reservation/reorder, allocation/upload, DMA, host launch/wait/relaunch, degree
and seed preparation, and ReGraph are outside this window on all arms.

## Declared Matrix

| Case | Vertices | Live edges | Total / updated shards | Logical / physical updates | Hot / DDR updates |
| --- | ---: | ---: | ---: | ---: | ---: |
| one-shard-64 | 131,105 | 393,315 | 3 / 1 | 64 / 128 | 128 / 0 |
| three-shard-4096 | 131,105 | 393,315 | 3 / 3 | 4,096 / 8,192 | 8,192 / 0 |
| five-shard-mixed-512 | 262,177 | 1,310,885 | 5 / 5 | 512 / 1,024 | 804 / 220 |
| empty | 131,105 | 393,315 | 3 / 0 | 0 / 0 | 0 / 0 |

Each case runs at memory latencies 64 and 128, for each of three arms: 24
observations, six nonempty timing comparisons and two empty controls. Every
source initially has one weight-3 edge in each destination shard. A logical
weight decrease is an exact delete of weight 3 followed by insertion of
weight 1; sources and shard pairs are unique. IDs are not compacted or
reordered. These are deterministic synthetic fixtures, not real temporal
workloads. All updated rows have one segment, so **binary search probes are
zero**; the earlier nineteen-input single-window study is still needed for
search-depth, repeated-row and large-batch coverage.

The separate [compact real-topology extension](real_inputs/README.md) now
adds 36 AU/SU/WK observations with multi-segment searches and exact replay of
these 24 synthetic rows. It passes the same complete state/traffic and 10%
prediction gates; maximum differences are 0.8971% for four banks and 2.3669%
for runtime mapping. Its derived compact batches are not original temporal
operations, and cache cost still dominates. This frozen synthetic capsule is
unchanged; the extension has its own raw evidence and regression capsule.

The complete cache requires 262,144 segments per shard. Smaller fixtures
therefore reserve empty tail segments in the last, non-updated source row.
The same layout is supplied to every arm. No live edge or update is added,
and this padding is not evidence of a real workload's memory footprint.

| Arm | Identity and resources |
| --- | --- |
| original-prepared-shards | Independent source16 finite original model; original default cache timing; four banks; sequential prepared shards |
| candidate-four-banks | Finite 8x8 registered search, 64 contexts/CU and 32 metadata credits/CU; complete hot cache; same four-bank duplicated metadata/PMA geometry; sequential prepared shards |
| candidate-runtime-23 | Same candidate through `GraSuShardedPmaUpdateSystem`; graph buffers mapped across 23 of 32 backend banks; runtime metadata sharing; sequential updated shards |

All use 200 MHz, 32 backend credits/bank, one bank acceptance/cycle and a
64-entry response depth. Candidate finite arbitration and cache schedules
remain assumptions awaiting HLS schedule, clock and whole-G resource checks.
Four-bank controls and the runtime topology are reported separately: they
are **not equal-resource configurations**. The original control adapts the
source-derived engine to prepared destination shards; it is not the
original paper's complete host/device pipeline.

## Checks And Evidence

All 24 observations passed state, operation and byte checks. Both declared
10% prediction tests passed. Positive differences below mean slower than
the prepared-shard original; negative differences mean faster.

| Case | Memory latency | Original cycles | Four-bank difference | Runtime-23 difference |
| --- | ---: | ---: | ---: | ---: |
| one-shard-64 | 64 | 532,775 | +0.0038% | -0.0206% |
| three-shard-4096 | 64 | 1,612,827 | -0.3416% | +0.0260% |
| five-shard-mixed-512 | 64 | 2,664,326 | +0.0144% | -0.0053% |
| one-shard-64 | 128 | 1,057,191 | +0.0019% | -0.0225% |
| three-shard-4096 | 128 | 3,193,947 | -0.1605% | +0.1726% |
| five-shard-mixed-512 | 128 | 5,286,918 | +0.0072% | -0.0124% |

The two empty controls had zero device cycles in every arm. The complete
run's bounded steps took 171.8 seconds in total; maximum recorded process
RSS was 1,230,744 KiB (1.174 GiB). CPU affinity was 127. CPU wall time and
these modeled device cycles are distinct quantities.

The [evidence index](evidence/index.json) owns the final decision and all
cycle comparisons. The [complete matrix](evidence/matrix.json) retains source,
library, compiler, input, binary, affinity and state hashes. The
[raw capsule](evidence/raw_runs.tar.gz) contains every execution's stdout,
stderr and resource record plus the declared input contract.

Every result requires full materialized PMA equality with the exact edit
oracle, full physical buffer checks (including untouched shards, non-owner
copies, metadata and padding), drained requests, and conserved update,
row, PMA read and write byte ledgers. Each touched shard pays 16 MiB PMA
reads and 16 MiB writes, plus one 64-byte read/write per DDR update. These
costs cannot be waived by the analysis or packager. Canonical state files
are the oracle form serialized **only after** complete physical equality,
not an unchecked device capture. Their full hashes and raw paths are kept
in the matrix; large state artifacts stay outside Git.

The 10% test applies to every nonempty declared comparison; failure is
reported rather than discarded. Empty rows have no speed ratio. A passing
prediction does not set `production_baseline_admitted`,
`hardware_timing_admitted`, `publication_match_admitted`, or
`host_inclusive_timing_admitted` to true. Fixed cache cost dominates these
small batches, so close total timing does not isolate search or DDR timing.

The checkpoint also passes 35 focused Python/organization tests and all 34
core CTest targets. The fresh serial core rerun took 338.7 seconds, with
maximum recorded process RSS 771,360 KiB, a 2-GiB address-space limit and
8-GiB reserve. Its raw log and resource record are retained under the raw
root's `verification-v1/` directory. The core stdout SHA-256 is
`5eea3339049bb0ee200f99867687417e60972fabba5a8a50ab79ea4c8c884ccb`;
the resource record SHA-256 is
`694a2d9deb009efc5e72e43a174639c3aa6aa8d7f30e8ab30465a3647d380804`.
Production numerical sources and SST integration are unchanged from the
preceding cached-handoff checkpoint; this checkpoint does not claim a new SST
run or hardware verification.

## Retained Preflight Failures

Raw root:
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-sharded-batch-v1`.
The pre-edit source archive pins commit `3912bab`; fresh source hashes in
the matrix identify the actual new harness.

- `smoke-v1`: original small fixture and five-shard runtime mixed fixture
  passed. Four-bank candidate rejected insufficient complete-cache geometry.
  The fix was explicit, identical empty tail reservation, not bypassing the
  production constructor guard.
- `smoke-v2`: driver attempted a build before configuring a fresh build
  directory. It failed before any numerical execution.
- `smoke-v3`: original passed; four-bank candidate rejected a destination
  window presented through the non-runtime single-window API. The harness
  now uses explicit runtime regions with the same four-bank addresses;
  destination ranges and validation remain intact.
- `smoke-v4`: fresh build and all three one-shard arms passed before the
  complete declared run. Earlier logs are preserved, not overwritten.

## Reproduce And Review

From the repository root, use a fresh output and the unchanged core libraries
from the complete cached-handoff checkpoint:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.study \
  --output /path/to/fresh-sharded-g \
  --core-build /path/to/cached-handoff/banked/compatibility/build/cpp

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.delivery \
  --matrix /path/to/fresh-sharded-g/results.json \
  --output /path/to/fresh-evidence

python3 -m unittest tests.test_grasu_sharded_batch -v
```

Runs are serial with a 2-GiB per-process address-space limit, an 8-GiB system
reserve, 600-second timeout and pinned CPU affinity. The runner refuses an
existing output or changed pinned source. This small study does not loosen
the separate 64-GiB routing admission threshold. That route's preceding
24-hour queue expired as `QUEUE_TIMEOUT_NOT_STARTED`; no routing result
exists from that attempt. Existing larger validation jobs retain their own
memory gates.

Code ownership is deliberately split:

- `cpp/tests/evaluation_impact/common_g/sharded/fixture.hpp`: inputs, oracle,
  byte helpers and canonical state encoding.
- `legacy.hpp`: independent original launch and complete four-bank checks.
- `candidate.hpp`: four-bank/runtime candidate execution and physical checks.
- `execution.cpp`: thin CLI and final operation/byte invariants.
- `spine_cycle_sim/experiments/evaluation_impact/common_g/sharded/`: separate
  preparation, bounded execution, analysis and packaging modules.

## Next Admission Gates

1. Actual temporal inputs and broader hot/cold occupancy under the same
   whole-batch contract. Multi-segment search now has separate compact
   real-topology coverage; it does not close the actual-temporal gate.
2. Search/cache HLS schedules, resource fit and hardware timing; no simulator
   agreement can substitute for these.
3. R credit/window controls and broader original-A/A4 comparisons, with all
   resource differences retained.
4. Measured host/seed windows and the physical integrated path, then a fair
   identical warm-state batch-to-convergence Spine diagnostic.

Do not replace Figure 7 or rescale Figures 8--11 from this diagnostic. The
[parent guide](../README.md#figure-impact-rules) states their distinct impact
rules and evidence boundaries.
