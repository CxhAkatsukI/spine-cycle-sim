# Warm-Batch CPU Preparation

This is a **partial CPU microbenchmark**, not a measured XRT driver, FPGA time,
host-inclusive speedup, or baseline-admission result. It supplements the
[common-warm device diagnostic](README.md) and its
[same-batch A4 control](SAME_BATCH_A4.md), without changing either frozen run.
No numerical-core, memory, HLS, FPGA, or paper change was made.

## Boundary Audit

The earlier `persistent_update_host_benchmark.cpp` includes initial Spine
snapshot construction and GraSU reorder/reservation/PMA construction. Adding
its total to this resident-state demo would charge cold preparation to a warm
boundary. Simulator execution wall time is not host orchestration time either.

This benchmark instead accepts the **same three insertion records and already
fixed device vertex IDs** as the saved smoke/Amazon diagnostic:

| Arm | CPU work measured | Not established by that measurement |
| --- | --- | --- |
| Spine | Copy three records, sort by `(src,dst)`, encode the actual 16-byte sort ABI, allocate/free the output | Host driver, DMA, dirty/active-state preparation, launch/wait, result readback |
| GraSU | Bin by 65,536-vertex destination partition, encode local destination and weight, stripe each shard across four lanes, pad empty lane allocations, sort/deduplicate source seeds, allocate/free the outputs | Applying seeds to resident state, clearing active bits, metadata refresh, buffer migration, task launch, round status decisions/relaunch, result readback |

The seed **list** is not an active-state patch. The production one-shot
`sharded_k4_native_host.cpp` builds a dense old-state vector, marks the source
seeds and migrates the initial buffers before its wall timer. That does not
prove a sparse resident per-batch patch API exists. Its initial state upload
must not be silently treated as a free working warm driver.

Read-only ABI references inspected, not compiled or timed here:

- `grasu-regraph-integration/include/weighted_pma_runtime_plan.hpp`,
  `pack_weighted_pma_runtime_buffers`: per-shard `update % 4` striping and
  minimum-one-word lane allocation. SHA-256:
  `e330e246bda0c1251f6e155173369b2faee10e94472417be8dbc00a47c1a6e4c`.
- `grasu-regraph-integration/tools/sharded_k4_native_host.cpp`: dense initial
  state/seed setup, migration, per-shard G tasks, per-round adapter/R tasks
  and status readback. SHA-256:
  `19eba0e30b1d0527b668fd2fe59d88392c1dcc4afc70255400fceedd5ab05b4d`.
- The benchmark calls the simulator's existing `encode_spine_sort_edges` and
  `encode_grasu_pma_edge`, linked against its hash-checked core library.

File parsing, graph/oracle construction, ID remapping and initial preload are
outside both CPU measurements. Inputs are already validated to their common
insertion ABI. These are **hot-cache, reused-small-batch** operation costs;
they do not estimate cold cache behavior, large batches or complete driver
costs. G's lane-allocation bytes include empty shards; they are not actual
DMA bytes or a claim that all allocated buffers must transfer per batch.

## Protocol And Results

Release `g++ -O3 -DNDEBUG -std=gnu++20`, no LTO, CPU 124. Each workload has
seven independent process repetitions. Every process performs 20 warmup
blocks per arm, then 100 timed blocks of 1,000 preparations per arm. Arm order
alternates by block; workload order alternates between repetitions. Allocation
and destruction are timed. An output escape prevents elimination without
adding checksum traversal to the interval. No samples are discarded and no
timer/loop overhead is subtracted. The reported point is the median of seven
process medians, not a confidence interval or single-call latency guarantee.

| Workload | Spine CPU median | G CPU median | Spine process-median range | G process-median range |
| --- | ---: | ---: | ---: | ---: |
| 96-vertex smoke, three updates | 0.0930 us | 0.1169 us | 0.0907--0.1134 us | 0.1124--0.1404 us |
| Amazon slice, three updates | 0.0891 us | 0.3183 us | 0.0882--0.0936 us | 0.3148--0.3334 us |

Adding **only these measured operations** to the existing predicted device
time does not change the direction of any row:

| Workload | Memory latency | Device G+R / Spine | Device plus partial CPU ratio | Extra unmeasured disadvantage needed to reach a tie |
| --- | ---: | ---: | ---: | --- |
| Smoke | 64 | 1.228099 | 1.228104 | Spine host minus G+R host = 0.123911 ms |
| Smoke | 128 | 0.722355 | 0.722406 | G+R host minus Spine host = 0.273189 ms |
| Amazon | 64 | 5.322593 | 5.322335 | Spine host minus G+R host = 2.615369 ms |
| Amazon | 128 | 5.274919 | 5.274774 | Spine host minus G+R host = 4.469429 ms |

The last column is **algebraic sensitivity**, not an assumed or measured
launch cost. It uses the common 150-MHz clock and subtracts the two device
times plus measured preparation. It excludes all remaining host work on
both sides. The machine-readable `full_host_inclusive_speedup` stays `null`.
Thus the measured small-batch CPU work is immaterial to this diagnostic's
direction; a complete host-inclusive claim remains **unavailable**.

The default-off R candidate still fails the 15% same-batch parity band on
three of four conditions, and the demo's G uses direct native segment RMW,
not the full-cache G candidate. This CPU benchmark does not close those gates,
strict resource matching, original-publication reproduction or wider workloads.

## Safety And Evidence

The final run had a 301,789,184-byte cgroup peak (287.81 MiB), zero swap and
92,842,684,416 available bytes at the final sample. Containment is exactly
6/5 GiB max/high with a 24-GiB reserve, atomic admission, single worker,
five-second watchdog, 4-GiB child address-space caps and finite timeouts.
An explicit final memory snapshot covers jobs shorter than the watchdog's
first sample. The first successful pilot predates that final-snapshot addition;
its complete samples, resources and source snapshot are also retained, not
discarded or relabeled as a failure. Preparation C++ and numerical core are
identical between the two attempts; the pilot is not pooled into final medians.

The [portable index](host_cpu/index.json) and archive contain both attempts,
all raw samples/commands/resources, input batches, the final memory snapshot,
compiler/core identities and the independent benchmark/runner source package.
Verification also requires the unchanged adjacent [device capsule](evidence/index.json),
which checks the old/final complete-state vectors and raw device matrix.
The raw final run is
`/data/chuxiao/experiments/warm_host_preparation_20261023/attempt-v2`.

The standalone ABI self-test checks sorting, complete round trips,
cross-partition/four-lane encoding, seed deduplication and rejected invalid
records. Focused Python tests reject missing repetitions/samples, changed
inputs/ABI and any attempted conversion to full-host timing. The numerical
core is unchanged; its 37 passing tests are reused by hash, not rerun here.
No SST or FPGA gate was run.

Delivery verification passed all 26 warm-comparison Python tests, nine cached-core
reuse tests, 15 repository-organization tests, documentation/catalog checks and
`git diff --check`. The standalone C++ ABI self-test passed in both attempts.

## Reproduce

Run from the repository root with a **fresh** path and unit name:

```bash
systemd-run --user --wait --pipe --collect --unit=spine-warm-host-rerun-v1 \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=1000 --working-directory="$PWD" \
  /usr/bin/python3 -m spine_cycle_sim.experiments.evaluation_impact.warm_comparison.host_study \
  --reference /data/chuxiao/experiments/r_gather_reuse_20261022/convergence-v2/results.json \
  --comparison /data/chuxiao/experiments/warm_spine_comparison_20261023/attempt-v6/results.json \
  --output /data/chuxiao/experiments/warm_host_rerun/attempt-v1 --cpu 124
```

Verify the delivered archive without those machine-local input directories:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.warm_comparison.host_delivery \
  --output docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/warm_comparison/host_cpu \
  --warm-evidence docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/warm_comparison/evidence
python3 -m unittest discover -s tests -p 'test_warm_host*.py' -v
```

To package a new run, add `--attempt /path/to/new-attempt` and change `--output`
to a fresh directory. The original capsule is never overwritten.
