# Compact Real-Topology G Controls

## Question And Scope

Does the preceding complete-cache G prediction retain prepared original G's
performance when edited rows require actual multi-segment searches? This
extends the [synthetic whole-batch study](../README.md), not the paper or a
frozen figure package. The finite search/cache candidate stays default-off.
No production timing, profile, SST component or HLS implementation is changed.

The input owner is the tracked
`configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json`.
Its graph, update and compact-ID mapping hashes are checked before execution.
These are unique non-self edges from **source file order**, not reconstructed
chronological order. Topology comes from AU, SU and WK; weights are synthetic.
Mixed edits and weight changes are derived workloads, not recovered original
temporal operations. Compact IDs change original partition occupancy.

## Declared Matrix

Each input has 8,192 live edges. Existing compact vertex IDs are unchanged;
one appended isolated vertex owns only empty PMA tail padding. All inputs fit
one destination shard. The two scenarios are frozen mixed-512 and
weight-change-4096 batches, in their existing record order. The latter has
8,192 physical delete/insert records, not 4,096 physical records.

| Dataset | Original compact vertices | Scenario | Physical updates | Multi-segment updates | Binary probes |
| --- | ---: | --- | ---: | ---: | ---: |
| AU | 3,409 | Mixed | 512 | 242 | 502 |
| AU | 3,409 | Weight change | 8,192 | 5,192 | 12,112 |
| SU | 3,224 | Mixed | 512 | 190 | 369 |
| SU | 3,224 | Weight change | 8,192 | 4,682 | 9,941 |
| WK | 5,930 | Mixed | 512 | 64 | 132 |
| WK | 5,930 | Weight change | 8,192 | 1,626 | 3,061 |

Six inputs x two memory latencies (64/128) x three unchanged arms give 36
observations. The arms are prepared original source16, finite candidate with
the same four banks, and candidate with the actual 23-channel runtime graph
mapping. They use the parent study's 200-MHz clock, 32 credits/bank, one bank
acceptance/cycle and 64-entry response depth. Runtime mapping is not claimed
to be equal-resource to four banks.

Every arm uses identical trace-aware reservation and complete 262,144-segment
cache footprint. Each launched shard pays 16 MiB reads and 16 MiB writes.
The empty tail is an explicit fixture transformation, not evidence that the
original compact graph needs that footprint. All edited segments are hot;
the earlier synthetic mixed case supplies separate DDR coverage. Fixed cache
cost still dominates these small batches, so close total time is not a
measurement of isolated search latency or of a full real temporal workload.

Timing starts with prepared resident input and ends after acknowledged final
writes. Host reservation/reorder, allocation/upload, DMA, launch/wait/relaunch,
degree/seed work and ReGraph are excluded on every arm. This is not host-inclusive
throughput, a measured FPGA speedup or published GraSU performance reproduction.

## Validation And Evidence

All 36 observations pass complete state, mutation, search and traffic checks.
The maximum absolute cycle difference from prepared original G is 0.8971%
for the four-bank candidate and 2.3669% for the runtime candidate. Both
predeclared 10% prediction tests pass. Positive differences mean slower:

| Input | Memory latency | Original cycles | Four-bank difference | Runtime difference |
| --- | ---: | ---: | ---: | ---: |
| AU mixed | 64 | 533,612 | +0.0302% | -0.0860% |
| AU mixed | 128 | 1,058,732 | +0.0137% | -0.0931% |
| AU weight change | 64 | 551,741 | -0.5599% | +1.8808% |
| AU weight change | 128 | 1,087,139 | +0.0314% | +2.3669% |
| SU mixed | 64 | 533,492 | +0.0352% | -0.0727% |
| SU mixed | 128 | 1,058,548 | +0.0057% | -0.0812% |
| SU weight change | 64 | 550,800 | -0.5664% | +1.4935% |
| SU weight change | 128 | 1,085,264 | -0.0183% | +1.9637% |
| WK mixed | 64 | 533,420 | +0.0292% | -0.0615% |
| WK mixed | 128 | 1,058,337 | +0.0037% | -0.0640% |
| WK weight change | 64 | 548,418 | -0.8971% | +0.6730% |
| WK weight change | 128 | 1,080,514 | -0.2659% | +1.2513% |

Bounded steps took 128.5 seconds in total, with maximum process RSS 354,216
KiB. The synthetic replay took 172.4 seconds with maximum RSS 1,230,820 KiB.
Both use CPU affinity 127; these are runner resource measurements, not device
timing. Every old observation and state hash is identical. No preflight or
matrix execution failed in this extension; earlier failures remain in the
parent study rather than being rewritten.

The checkpoint passes 60 focused Python/evidence/organization tests plus the
documentation-layout, catalog and diff checks. Both fresh C++ harness builds
and every matrix execution pass. Production numerical sources and SST are
unchanged; this extension does not claim a new full core CTest, SST or HLS
run. The parent checkpoint retains its 34-target core regression evidence.

The unchanged synthetic 24-row matrix is replayed first. Every observation
(including cycles and traffic) and complete canonical state hash must equal
the preceding committed checkpoint before any new real-input result is
interpreted. The [regression capsule](regression/index.json) retains that replay;
the old [reference matrix](../evidence/matrix.json) is not overwritten.

The [real-input index](evidence/index.json) and [complete matrix](evidence/matrix.json)
own the results. Each capsule includes stdout, stderr, process resource logs
and its declared contract. The real-input archive additionally contains all
13 pinned source-contract, graph, batch and ID-mapping files. Full canonical
states remain hash-indexed outside Git; they are serialized only after full
physical equality, including metadata, non-owner copies and empty padding.

Independent Python and C++ oracles count successful mutations and each binary
probe; an edge-set oracle additionally checks the final weighted graph.
Search, row, operation and physical byte ledgers must agree in every arm.
Each input's state hash must also agree across both latency assumptions.
Missing rows, omitted cache cost, divergent states and changed pins fail
closed. A timing mismatch is retained as a finding, not discarded.

The +/-10% prediction test applies to all 12 nonempty comparisons. Passing it
does not admit production baseline, HLS feasibility, hardware timing,
host-inclusive timing or original-publication performance. The original
source16 versus paper8 geometry and publication workload denominator remain
separate unresolved questions.

## Reproduce And Review

Use fresh output directories and the unchanged core libraries from the
cached physical-handoff checkpoint:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.real_study run \
  --output /path/to/fresh-real-g \
  --core-build /path/to/cached-handoff/banked/compatibility/build/cpp

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.real_study package \
  --matrix /path/to/fresh-real-g/results.json \
  --output /path/to/fresh-evidence

python3 -m unittest tests.test_grasu_sharded_real tests.test_grasu_sharded_batch -v
```

Run the parent's synthetic runner and packager separately for the regression
capsule, then compare every old observation and state hash. Both runners use
serial execution, a 2-GiB process address-space limit, 8-GiB available-memory
reserve, 600-second per-command timeout and pinned CPU affinity. These limits
do not loosen the separate R campaign or routing admission thresholds.

Raw root:
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-sharded-real-v1/`.
The pre-edit archive pins `29d17c4`; `smoke-v1/source.tar.gz` and its diff record
freeze the new harness before smoke execution. `smoke-v1/`, `replay-v1/` and
`attempt-v1/` retain separate outputs. No failed or earlier output is reused.
The pre-edit archive is retained at
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-sharded-batch-v1/pre-real-inputs-29d17c4.tar.gz`
with SHA-256
`803b79edb9d183e6eaba8b994bb64b95b0a3e7f494753c70eccd532baf45b17c`.

Ownership remains small: `real_inputs.py` validates inputs and counts work,
`real_analysis.py` checks the complete matrix, and `real_study.py` is a thin
CLI over the parent's bounded runner/packager. The C++ `real_fixture.hpp`
owns input/oracle construction and `real_execution.cpp` owns the CLI; both
reuse unchanged original/candidate execution and physical checks. Existing
synthetic fixtures and numerical execution do not gain a new timing mode.

Next: actual temporal and broader occupancy coverage, search/cache HLS
schedule and resource checks, remaining R resource controls, measured host
windows and an integrated warm-batch-to-convergence Spine diagnostic. This
study alone cannot replace Figures 7--11.
