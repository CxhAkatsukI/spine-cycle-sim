# Chronological First-Contact G Diagnostic

## Decision

**The complete four-bank prediction passes the declared 10% test; the actual
runtime-mapped prediction does not.** All 36 observations pass full physical
state, search, mutation and traffic checks. The six 64K runtime comparisons
are 22.7--35.5% slower than prepared original G. They remain in the delivered
matrix. Do not admit the baseline or replace any evaluation figure from this
result. The candidate stays default-off; numerical core, SST, HLS, paper and
frozen figure sources are unchanged.

This extends the [compact derived-batch study](../real_inputs/README.md), whose
small batches were cache-cost dominated. It tests larger updates in actual
timestamp order, but **not the original GraSU publication workload**: repeated
contacts and self-loops are explicitly removed, remaining first contacts
become unit-weight insertions, and vertex IDs are compacted. Original temporal
insert/delete conversion, source16 versus paper8 geometry, and publication
throughput denominator remain separate unresolved questions.

## Inputs And Window

The source authority is
`configs/experiments/grasu_publication_workload_admission_v1.json`; its pinned
AU, SU and WK compressed sources are read completely into bounded disk SQLite.
Selection is ordered by `(timestamp, original event position)`, including ties.
The first 8,192 unique non-self directed contacts form the initial graph.
The next 4,096 and 65,536 contacts are independent insertion prefixes starting
from that same initial graph, not two successive batches. Weight is one.

The ID mapping uses first encounter across base plus the largest future batch.
Both sizes share that mapping and vertex extent, including future isolated
IDs. An additional isolated source owns empty complete-cache tail padding.
All arms receive identical trace-aware reservation; its host cost is excluded
on all arms and cannot be called free in a later host-inclusive comparison.

| Dataset | Compact vertices before padding | Full source events | Selected contacts | Excluded repeats / loops in scanned prefix |
| --- | ---: | ---: | ---: | ---: |
| AU | 15,865 | 964,437 | 73,728 | 22,479 / 24,540 |
| SU | 9,630 | 1,443,339 | 73,728 | 16,258 / 18,767 |
| WK | 19,933 | 7,833,140 | 73,728 | 85,420 / 58,137 |

| Input | Physical insertions | Multi-segment updates | Independent binary probes |
| --- | ---: | ---: | ---: |
| AU 4K | 4,096 | 2,438 | 5,656 |
| AU 64K | 65,536 | 42,404 | 138,698 |
| SU 4K | 4,096 | 2,185 | 4,466 |
| SU 64K | 65,536 | 44,949 | 133,033 |
| WK 4K | 4,096 | 3,035 | 9,846 |
| WK 64K | 65,536 | 52,197 | 191,103 |

Six inputs x two memory latencies (64/128 cycles) x three arms give 36 rows:
prepared source-derived original G, finite candidate on four banks, and finite
candidate through the actual 23-channel runtime allocator. The latter denotes
the graph-channel budget, not a claim that this single shard uses 23 banks at
once. All use 200 MHz, 32 backend credits/bank, one acceptance/cycle and
64-entry response depth. Four banks matches physical bank count, not every
master/queue or HLS resource. Runtime and original resources differ explicitly.

Each touched shard pays the complete 262,144-segment cache's 16 MiB preload
and 16 MiB writeback. All edited segments are hot. Timing begins with resident,
prepared inputs and ends at acknowledged final writes; host preparation,
allocation/upload, DMA, launch/wait/relaunch, degree/seed preparation and R are
excluded on every arm. This is declared simulator timing, not FPGA timing.

## Complete Results

Positive differences mean more cycles than prepared original G.

| Input | Memory latency | Original cycles | Four-bank difference | Runtime difference |
| --- | ---: | ---: | ---: | ---: |
| AU 4K | 64 | 543,580 | -0.3665% | +0.3670% |
| AU 4K | 128 | 1,074,896 | -0.1377% | +0.6196% |
| AU 64K | 64 | 670,555 | +4.0783% | +25.0172% |
| AU 64K | 128 | 1,330,507 | +2.6301% | +23.1031% |
| SU 4K | 64 | 542,872 | -0.4461% | +0.1654% |
| SU 4K | 128 | 1,073,560 | -0.1735% | +0.4079% |
| SU 64K | 64 | 667,850 | +4.5259% | +24.3472% |
| SU 64K | 128 | 1,324,666 | +3.0442% | +22.6679% |
| WK 4K | 64 | 545,813 | -0.3908% | +1.3023% |
| WK 4K | 128 | 1,079,253 | -0.1408% | +1.5122% |
| WK 64K | 64 | 697,212 | +4.7100% | +35.4614% |
| WK 64K | 128 | 1,383,143 | +3.0557% | +34.0094% |

The four-bank candidate remains within 4.71% on every comparison. Runtime is
within 1.52% for 4K, but fails all six 64K comparisons. Relative to the same
candidate on four banks, the 64K runtime path takes 18.96--30.04% more cycles.
The previous small-batch success therefore does not generalize to this scope.

Static inspection shows a meaningful difference: `grasu_sharded_update.cpp`
maps every CU to one row region and one binary region per shard. The four-bank
control has duplicated metadata across four banks. Larger probe counts can
expose that shared-bank contention. This is a **cause to test**, not a measured
stage attribution: the current capsule records total windows and conserved
work, not sufficient per-stage/port timelines to assign the entire difference.
Do not change memory latency or original-G timing to remove it.

Next isolate metadata-bank contention and search progress using read-only
counters and explicit resource controls. A correction must have an actual
data-layout/HLS realization, account for any replicas/buffering and host
maintenance, preserve this matrix, and rerun all regressions. Passing a
four-bank control alone cannot admit the runtime baseline. HLS II/clock/fit,
broader hot/cold temporal workloads, R resource controls, measured host windows
and an integrated warm-state-to-convergence Spine comparison remain open.

## Evidence And Retained Failure

- [New matrix](evidence/index.json): all 36 chronological rows, complete state
  hashes, input/source/binary pins and raw stdout/stderr/resources.
- [Pre-reader replay](regression/index.json): all 36 preceding real-topology
  rows match every observation and canonical state hash before the reader edit.
- [Post-reader replay](parser_regression/index.json): the same exact 36-row
  agreement after the experiment input reader changed. No sorted-batch or
  production maintenance behavior was relaxed.
- [Preflight](preflight/index.json): all 36 initial commands were rejected
  before timing because the reused Spine maintenance loader required `src,dst`
  sorting. Zero numerical observations resulted. The fix was a strict,
  experiment-only **order-preserving** reader, not sorting the batch. The
  capsule also retains its C++ format tests, six successful AU smoke runs and
  both fresh experiment source archives.

The original and candidate must agree with an independent weighted edge-set
oracle, exact segment edits, full physical PMA/non-owner copies/metadata/padding,
and independent Python/C++ search counts. Per-case final state hashes agree
across every arm and memory latency. Requests drain and byte counts conserve;
all source, input and binary pins are checked again before completion.
Canonical states are oracle form serialized only after complete physical
equality, not unchecked device captures; large state files stay outside Git.

Preparation took 31.3 seconds (maximum process RSS 164,808 KiB). New bounded
matrix steps took 196.0 seconds (364,104 KiB maximum RSS). Pre-/post-reader
replay steps took 131.0 / 129.8 seconds (353,160 / 361,868 KiB maximum RSS).
These are CPU runner measurements, separate from predicted device cycles.
The runs were serial with a 2-GiB process address-space limit, 8-GiB system
reserve and CPU affinity 127 for matrix executions. Preparation has a
900-second command limit; matrix commands have 600 seconds. Existing larger
HLS/R/route reservations were not weakened, and no hardware build was started.

Raw root:
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-chronological-v1/`.
`pre-edit-14b9557.tar.gz` pins the parent commit; SHA-256 is
`b3d79b5e171903c2af14eff28bc8305c96a1e05b2b802315bbe1296a5a900315`.
`source-v2.tar.gz` freezes the numerical harness before the corrected run;
SHA-256 is
`959327d82530d02ff19e8f46db863dd218713c655dc6946349ff6de8f068d541`.
Existing output directories and earlier capsules were not reused.

## Reproduce And Review

Use fresh paths and unchanged core libraries from the cached-handoff build:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.chronological_study prepare \
  --output /path/to/fresh-inputs

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.chronological_study run \
  --prepared /path/to/fresh-inputs --output /path/to/fresh-run \
  --core-build /path/to/cached-handoff/banked/compatibility/build/cpp

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.chronological_study package \
  --matrix /path/to/fresh-run/results.json --output /path/to/fresh-evidence

python3 -m unittest tests.test_grasu_chronological_inputs tests.test_grasu_sharded_real \
  tests.test_grasu_sharded_batch -v
```

Replay `sharded.real_study` into another fresh directory and compare all old
observations/state hashes before interpreting new results. The C++ reader test
is target `ordered_g_input_test` in `cpp/tests/evaluation_impact/common_g`;
configure with `CORE_BUILD`, build serially and run CTest in that fresh build.

Ownership remains separated: `chronological_inputs.py` selects and materializes
inputs, `chronological_contract.py` checks provenance and declares work,
`chronological_study.py` is the thin CLI over the unchanged shared runner,
and `real_analysis.py` owns fail-closed numerical checks. C++
`ordered_input.hpp` owns the narrow four-field experiment format and preserves
order; fixture/oracle construction and numerical execution keep their existing
owners. No alternate production architecture or hidden timing factor is added.

Verification: all 55 focused input, delivery, whole-batch, cached-handoff,
finite-search and repository-structure tests pass, as do document/catalog
audits and `git diff --check`. The new C++ reader builds with warnings as errors
and passes CTest. Core and SST are unchanged; their full suites were not rerun
for this experiment-reader change. Both 36-row before/after numerical replays
are included rather than substituting a compile-only equivalence claim.
