# G Search Concurrency And Reference Forwarding

## Question And Decision

The preceding [cached-G study](../cached_hot/README.md) preserves state and
traffic but remains 60--65% slower than the legacy original on large batches.
This study isolates two observable implementation differences without fitting
memory latency or granting additional AXI ports or credits:

- `original_forwarded` permits pending same-row cache forwarding at the
  source/RTL-derived three-cycle interval and seven-cycle latency. The old
  `original` arm remains unchanged. This is a reference timing control, not
  a claim that complete original G has been calibrated on FPGA.
- `cached_hot64` expands the candidate's search contexts from 16 to 64 per CU,
  keeping its existing metadata master and finite physical memory resources.
  The 16-context `cached_hot` arm remains unchanged. More contexts have a
  real buffering/arbitration cost; integrated HLS fit and clock remain open.

All 266 observations completed with state/work/traffic checks passing and
all 190 previous observations exactly reproduced. The complete 10% performance
gate still fails. No production profile, routed bitstream, paper, or frozen
figure handoff is changed. This is a diagnostic, not an admitted baseline.

## Results

Ratios below are candidate cycles divided by forwarded-original cycles;
less than one is faster. Both latency assumptions and every declared case
remain in [the complete evidence](evidence/index.json), including failures.

| Input | Updates | Latency 64 | Latency 128 |
| --- | ---: | ---: | ---: |
| Mixed | 4096 | 1.060 | 1.059 |
| Mixed | 8192 | 1.128 | 1.122 |
| Mixed | 16384 | 1.232 | 1.220 |
| Mixed | 65536 | 1.551 | 1.525 |
| Same key | 4096 | 1.046 | 1.053 |
| Same key | 65536 | 1.553 | 1.525 |
| Hot only | 65536 | 1.550 | 1.525 |

Raising contexts alone improves the large-batch candidate by about 5--6%,
not enough to close the gap. Reference forwarding preserves all state and
traffic, but is not the main explanation for these large-batch differences.
Tiny and empty inputs include full-cache fixed costs and must not be used
alone as throughput evidence.

The original has eight metadata masters per CU, while the candidate still
shares one. Port contention, update reading and stage overlap need measured
diagnostics before attributing the remaining gap. This table does not prove
that additional ports would solve it. No latency multiplier or fitted
coefficient was introduced.

## Fixed Matrix And Boundary

There are 266 observations: the same nineteen inputs, 64/128-cycle memory
assumptions, and seven arms. All 190 previous observations must reproduce
exactly: cycles, work, physical traffic, and full PMA state hashes. The two
new arms add 76 controls; none of the old failures may be dropped.

The inherited inputs include empty/tiny batches, neighboring sizes,
hot/cold boundaries, mixed batches through 65536 updates, repeated-key
conflicts, owner aliases, and cold reuse. Every nonempty case contributes
to the declared 10% tests, separately for both memory latencies.

All arms receive the same ordered batch and prepared resident PMA. Timing
covers update execution, complete cache preload/writeback where present,
cold writes, all memory acknowledgements, and memory drain. Host preparation,
DMA, launch, graph propagation, and host orchestration are excluded from
every arm. This is not a complete dynamic graph comparison with Spine.

Clock remains 200 MHz, with four physical banks and 32 bank credits. Cache
geometry remains two 8-MiB halves, sixteen banks per half, depth-two bank
queues, and three-entry bank pipelines. Original search has eight metadata
AXI masters per CU; the compact candidate has one. Matching the number of
contexts does not make these architectures resource-identical.

## Checks And Code Ownership

Fresh Release core verification passes all 31 CTest targets. The added cache
test checks same-row and alias forwarding, delayed retirement, full-state
writeback, ends, finite queues, all beats/acknowledgements, and both scheduler
registration orders. Search tests exercise both context counts, neighboring
batch lengths, invalid metadata, and rejected undeclared geometry.

Python analysis rejects missing or duplicate rows, changed historical output,
changed physical traffic or logical work, zero-time cache controls, resource
changes, and unsupported promotion of hardware/publication admission.
One slow conflicting row fails the performance gate; averaging cannot hide it.

The [regression capsule](verification/index.json) records 92 focused Python
tests, a fresh SST build and three default SST checks. Default memory/native
JSON results reproduce the preceding checkpoint exactly; these are not
64-context candidate SST timing calibration. The historical frozen-hash suite
still fails: 27 earlier mismatches plus three explicitly listed original-G
source changes. Its old manifests are unchanged. Earlier Python attempts,
including a rejected test fixture and the historical-audit rejection, are
retained with their logs rather than reported as passing.

| Responsibility | Owner |
| --- | --- |
| Explicit context count and default-off validation | `cpp/include/spine_sim/grasu.hpp`, `cpp/src/grasu.cpp` |
| Finite context scheduling and response ownership | `cpp/src/grasu_update/parallel_search.cpp` |
| Default-off original pending-value forwarding | `cpp/src/original_grasu/hot_store.cpp` |
| Shared seven-arm complete-state execution | `cpp/tests/evaluation_impact/common_g/execution.cpp` |
| Finite cache and search checks | `cpp/tests/original_grasu/cache_tests.cpp`, `cpp/tests/grasu_parallel_search_tests.cpp` |
| Shared bounded execution and compact packaging | `spine_cycle_sim/experiments/evaluation_impact/common_g/runner.py`, `delivery.py` |
| Declaration and numerical admission | `spine_cycle_sim/experiments/evaluation_impact/common_g/search_concurrency/` |
| Matrix rejection tests | `tests/test_grasu_search_concurrency.py` |
| Capsule integrity and historical-delta rejection tests | `tests/test_grasu_search_delivery.py` |

Cached-G and this study share one bounded runner and one packaging owner;
the earlier cached-G public CLI and report schema remain compatible.
The 190 exact replays also verify that extraction numerically.

## Reproduction And Safety

```bash
cmake -S . -B /path/to/fresh-core -DCMAKE_BUILD_TYPE=Release
cmake --build /path/to/fresh-core -j1
ctest --test-dir /path/to/fresh-core --output-on-failure -j1

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.search_concurrency.study \
  --output /path/to/fresh-matrix --core-build /path/to/fresh-core/cpp \
  --previous /path/to/frozen-190-row-cached-G/results.json

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.search_concurrency.delivery \
  --output /path/to/fresh-evidence --matrix /path/to/fresh-matrix/results.json \
  --previous /path/to/frozen-190-row-cached-G/results.json

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.search_concurrency.verification \
  --base /path/to/complete-checkpoint --previous /path/to/preceding-checkpoint \
  --output /path/to/fresh-regression-capsule

python3 -m unittest discover -s tests -p 'test_grasu_search_concurrency.py'
```

The pre-edit source archive and manifest, fresh core, raw executions, complete
PMA states, and build configuration are under
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-search-concurrency-v1/`.
Runs are serial, with a 1-GiB per-process address-space limit, 8-GiB admission
reserve, and 600-second per-step timeout. The fresh core build peaks at
701716 KiB process RSS; matrix processes peak at 342392 KiB. The fresh SST
build uses a separate 2-GiB address-space limit and 9-GiB reserve and peaks at
1020224 KiB process RSS. Heavy routing and full-cache HLS retain their separate
queued admission thresholds; these lightweight controls do not authorize
their launch or change their pinned sources.

## Remaining Gates

Even a complete predicted timing match would not establish a published-paper
match, current routed hardware performance, or a production baseline. Whole-G
clock/resource evidence, weighted/cold coverage, temporal workload admission,
actual G-to-adapter/R handoff, and the separately measured host window remain
required by the [overall plan](../PLAN.md). No new Spine demo is admitted here.
