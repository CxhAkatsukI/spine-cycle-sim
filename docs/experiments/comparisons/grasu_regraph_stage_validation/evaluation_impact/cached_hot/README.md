# Full-Depth Cached G: Prediction Checkpoint

## Decision And Scope

This is an explicit, default-off simulator candidate, not the current routed
G implementation. It restores two source16 hot caches while retaining the
parallel-search candidate and unchanged cold processing. No production
profile, paper or frozen figure handoff is replaced.

The complete declared study contains 190 observations: nineteen inputs,
two unchanged memory latencies and five arms. The earlier 152 observations
must reproduce exactly, including cycles, physical traffic, logical work
and full output-state hashes. The completed [matrix](evidence/matrix.json)
passes those checks, but fails both declared 10% performance tests against the
legacy reference. [Delivery index](evidence/index.json) and
[regression index](verification/index.json) keep baseline admission false.

The legacy original-G model conservatively blocks same-row updates until
retirement. Original-source RTL supports a three-cycle interval, including
the tested same-row stream. Consequently, closeness to that legacy model
alone cannot admit a performance-retaining G baseline. Its explicit timing
correction, complete G/HLS timing and publication reproduction remain open.
Read the [admission plan](../PLAN.md) for the full exit criteria.

## Completed Results

Ratios below are candidate cycles / legacy-original cycles; above one is slower.
Every nonempty declared row participates in the gate, not just these examples.

| Input | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| 4096 mixed updates | 1.075 | 1.072 |
| 8192 mixed updates | 1.154 | 1.143 |
| 16384 mixed updates | 1.275 | 1.255 |
| 65536 mixed updates | 1.646 | 1.601 |
| 4096 same-key updates | 1.025 | 1.047 |
| 65536 same-key updates | 1.645 | 1.601 |
| 4096 owner-alias updates | 1.061 | 1.066 |

Caching reduces the 65536 same-key candidate time by about 4.65--4.72x
relative to direct hot owners. It is not universally faster: the 65536 mixed
case is 1.34--1.37x slower than direct owners, and very small batches pay the
full preload/writeback cost. Original and cached physical traffic agree on
all 38 input/latency pairs; complete states and logical work agree across
all five arms. All 152 prior observations reproduce exactly.

Fresh Release verification passes all 30 CTest targets, including finite
cache/backpressure/malformed-input checks. The fresh SST plugin builds, loads,
and produces exactly the previous default memory/native smoke results.
These smokes are default-path regressions, not candidate SST timing evidence.
The related Python selection passes 80 tests. The separately run historical
identity suites still fail 27 hash subassertions, with exactly the failure
set already present at `d510ea3`; their manifests were not rewritten.

Failed attempts are retained. The first cache test exposed an incorrect parent
read-acknowledgement size expectation; the corrected test requires the full
8-MiB acknowledgement and all ordered beats. The first complete matrix was
rejected by an analyzer that incorrectly required nonzero time for an empty
direct path. After correcting that check, a fresh 190-run matrix reproduces
all first-attempt numerical observations and complete-state hashes exactly.
Both failures and their logs are in the regression archive.

## Architecture And Costs

Each hot CU owns 131072 sixteen-word segments: 8 MiB per half, 16 MiB total.
Sixteen bank owners per half have depth-two input queues and finite
three-entry pipelines. The declared update interval is three cycles and
latency seven cycles. Same-row edits forward logically in input order;
external PMA state does not change until writeback. These assumptions are
grounded in the [isolated cache controls](../cache_probe/README.md), not a
calibrated complete-G implementation.

Every execution, including empty input, pays a full 16-MiB preload and
16-MiB writeback through the existing shared hot AXI masters. Load completion
requires every ordered data beat and the parent acknowledgement. Store
completion requires its acknowledgement. The finite queues, degree-output
backpressure, cold RMW traffic and memory drain are not omitted.

This is not a hidden cache inside the direct-HBM model. The direct processor
and all default configurations remain unchanged. The new configuration is
rejected outside its declared single-window, source16, parallel-search
geometry, and cannot be combined with direct hot owners.

Original isolated full-cache synthesis reports 256 URAM per half. Two halves
therefore require 512 before search, cold processing and ReGraph storage.
This arithmetic is not a placed-and-routed fit result. Integrated search
timing remains unresolved; its earlier isolated estimate missed 200 MHz.
The registered full-cache HLS comparison is separately memory-queued and is
not counted as completed evidence here.

The search resource choice also differs; the cache does not restore it:

| Search resource, per kernel | Independent original | Current parallel candidate |
| --- | --- | --- |
| In-flight update contexts | 64 | 16 |
| Row/binary-table AXI masters | 8 (four of each) | 1 shared |
| Update reader | Separate streamed reader | Per-context requests on one master |

The original source declares eight `m_axi` bundles in `kernel_bin_search.cpp`;
the source-derived model owns those ports in `cpp/src/original_grasu/search.cpp`.
The candidate is explicitly implemented in
`cpp/src/grasu_update/parallel_search.cpp`. Physical memory banks and service
assumptions remain common, but logical ports, contexts and buffering are not
identical. These differences are plausible remaining throughput constraints,
not yet an isolated measurement of their contribution.

## Matrix And Boundary

The five arms are independent legacy original G, unchanged current G,
parallel search, parallel search plus direct hot owners, and parallel search
plus the explicit full-depth cache. Inputs include empty/tiny batches,
hot/cold boundaries, neighboring sizes, mixed/dispersed batches through
65536 updates, repeated same-segment updates, owner aliases and cold reuse.
No failed row may be removed or averaged away to pass the 10% test.

Common assumptions are 200 MHz, four physical memory banks, 32 bank credits
and separately declared 64/128-cycle memory service. All arms receive the
same prepared PMA and ordered batch. Timing covers resident execution through
all update, cache and cold write acknowledgements and memory drain. Host
preparation, DMA, launch and propagation are outside every arm's window.

Complete state and logical work must agree across all five arms. Cached
traffic must equal original traffic and must independently equal direct-owner
traffic minus per-hot-update RMW plus the full-cache transfers. Empty input
is a fixed-overhead control, not a throughput data point.

## Code Ownership

| Responsibility | Owner |
| --- | --- |
| Explicit cache contract and finite pipeline constants | `cpp/include/spine_sim/grasu_update/cached_processor.hpp` |
| Cache load, bank queues, forwarding, retirement and writeback | `cpp/src/grasu_update/cached_processor.cpp` |
| Configuration validation, existing masters and system composition | `cpp/include/spine_sim/grasu.hpp`, `cpp/src/grasu.cpp` |
| Five-arm execution and complete-state oracle | `cpp/tests/evaluation_impact/common_g/execution.cpp` |
| Input matrix, bounded execution, admission checks and packaging | `spine_cycle_sim/experiments/evaluation_impact/common_g/cached_hot/` |
| Finite pipeline and malformed-input tests | `cpp/tests/grasu_cached_processor_tests.cpp` |
| Matrix, traffic, pin and package rejection tests | `tests/test_grasu_cached_hot.py` |
| Archived evidence integrity checks | `tests/test_grasu_cached_hot_delivery.py` |

## Reproduction And Safety

Build in fresh directories. Do not rebuild a frozen evidence binary in place.
The study records source/input/library/executable identities, compiler/CMake
versions, flags, CPU affinity, stdout/stderr and resource reports. Packaging
rechecks every live pin, full output-state hash and derived summary.
Raw per-run logs are delivered in one `raw_runs.tar.gz` with member hashes,
not hundreds of loose files. Full PMA states remain machine-local and indexed
by complete-state hashes rather than adding gigabytes of duplicate state to Git.

```bash
cmake -S . -B /path/to/fresh-core -DCMAKE_BUILD_TYPE=Release
cmake --build /path/to/fresh-core -j1
ctest --test-dir /path/to/fresh-core --output-on-failure -j1

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.cached_hot.study \
  --output /path/to/fresh-matrix --core-build /path/to/fresh-core/cpp \
  --previous /path/to/frozen-152-row-hot-owner/results.json

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.cached_hot.delivery \
  --output /path/to/fresh-evidence --matrix /path/to/fresh-matrix/results.json \
  --previous /path/to/frozen-152-row-hot-owner/results.json

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.cached_hot.verification \
  --base /path/to/completed-cache-study --previous /path/to/previous-hot-owner-study \
  --output /path/to/fresh-verification

python3 -m unittest tests.test_grasu_cached_hot tests.test_grasu_cached_hot_delivery -v
```

Runtime artifacts are under
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-cached-processor-v1/`.
Matrix execution is sequential with a 1-GiB per-process address-space bound,
8-GiB launch reserve and 600-second per-step timeout. The earlier identical
size matrix's maximum reported process RSS was 342244 KiB. Heavy HLS/routing
retain their separate, higher memory admission thresholds; this lightweight
study does not authorize them to launch. The cached execution peak process RSS
is 231296 KiB (341952 KiB including its harness build); fresh core and SST
builds peak below 1 GiB. Source snapshots,
binary/plugin hashes, compiler flags and machine-local state paths are indexed;
large duplicate source/state files are not added to Git.

## Remaining Gates

1. Correct the original model's same-row timing in a separately declared
   configuration, preserving the legacy matrix exactly; rerun all controls.
2. Validate search/cache/cold composition and achieved integrated HLS timing,
   not just source-functional compatibility or isolated bank schedules.
3. Extend G to real temporal inputs and supported shard geometries; establish
   independent FPGA/publication timing and report resources explicitly.
4. Complete R resource/workload controls, actual G-to-adapter/R handoff and
   host windows before the common warm-state Spine demo and figure review.

The next numerical control must separate cache forwarding from search
concurrency: preserve the legacy original arm, add an explicit source-grounded
forwarding reference, and test declared context counts with unchanged physical
memory service. Do not change the original latency or remove preload/writeback
to make a ratio pass. New contexts/ports need explicit resource accounting and
integrated HLS validation before they can replace the routed baseline.
