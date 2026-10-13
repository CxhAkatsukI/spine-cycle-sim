# Segment-Ordered Hot Updates: Prediction Checkpoint

## Decision

**G is still not admitted as a performance-retaining baseline.** Explicit hot
concurrency substantially improves the uncached candidate, but large dispersed
batches remain 17--23% slower than the independent original-G model. A large
same-segment batch is 7.4--7.8x slower. These failed rows are included, not
removed from the acceptance matrix.

This is a default-off, single-window simulator experiment, not production HLS,
FPGA calibration or a reproduction of a published GraSU throughput. The
[baseline admission plan](../PLAN.md) remains open. No paper text, production
profile, bitstream or frozen figure package is replaced.

## What Changed

The earlier [parallel-search candidate](../parallel_search/README.md) retained
one direct-HBM hot read/modify/write lane per hot CU. This experiment keeps
its search architecture and changes only that processor to sixteen bounded
owners behind the **same shared AXI master**. It does not add an implicit
URAM cache, free reads, ports or memory bandwidth.

Each physical segment maps to one owner. That owner waits for the previous
write acknowledgement before starting its next update. Different owners may
overlap their read and write waits. Different segments that hash to the same
owner serialize too; alias tests exercise this cost. Within the declared
single-window geometry, this preserves same-segment read-after-write order.
Publication uses the existing finite input, owner and degree-output queues.
Each master issues at most one read or write request per cycle; writes have
priority. Response handling, memory contention and outstanding limits remain
explicit in the existing AXI/backend components.

The processor and shared PMA-word helpers were extracted from `grasu.cpp`
before enabling the candidate. Twelve representative default-path runs
reproduce their pre-extraction observations exactly. The complete subsequent
matrix reproduces all 84 earlier original/current/search observations,
including cycles, traffic, logical work and complete PMA state hashes.

## Matrix And Boundary

All four arms receive the identical prepared initial PMA and ordered update
words: independent original source16 G, unchanged current G, parallel search,
and parallel search plus hot owners. Nineteen cases run at two fixed memory
latencies, giving **19 x 2 x 4 = 152 observations**. The five added cases are
4096/65536 repeated same-segment updates, 4096 distinct hot segments aliasing
one owner, 65536 dispersed hot updates, and 4096 repeated cold updates.
Every earlier case remains, including empty/tiny, hot/cold, lane boundary,
neighboring and mixed batches through 65536 updates.

Common controls: 200-MHz model clock, four physical memory banks, 32 bank
credits, identical segment geometry and declared 64/128-cycle memory service.
Timing begins with resident prepared update execution and ends after all RMW
write acknowledgements and memory drain. Host preparation, DMA and launch
are excluded on every arm. These assumptions are fixed, not fitted to results.
Empty input tests fixed overhead and is excluded from throughput gates.

All four arms agree on complete PMA state, hot/cold update counts, row reads
and binary probes. All three direct-HBM arms also have exactly equal physical
read/write traffic. Original G's physical traffic is allowed to differ because
its fixed hot-cache preload/writeback is real work in that model. Both the
one-sided no-more-than-10%-slower and two-sided 10% matching gates fail over
the full nonempty matrix.

## Results

Cycles below are predictions. A candidate/original ratio above one is slower.

| Memory latency | Case | Updates | Original G | Current G | Search only | Search + hot owners | Candidate/original |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 64 | Mixed | 4096 | 577403 | 1441620 | 289742 | 92283 | 0.160 |
| 128 | Mixed | 4096 | 1142267 | 2740180 | 549070 | 173563 | 0.152 |
| 64 | Mixed | 16384 | 700900 | 5806932 | 1168334 | 371067 | 0.529 |
| 128 | Mixed | 16384 | 1389287 | 11037652 | 2214094 | 698107 | 0.502 |
| 64 | Mixed | 65536 | 1206069 | 23268180 | 4682702 | 1486203 | 1.232 |
| 128 | Mixed | 65536 | 2384885 | 44227540 | 8874190 | 2796283 | 1.172 |
| 64 | Same segment | 65536 | 1207344 | 23282238 | 9373101 | 9373101 | 7.763 |
| 128 | Same segment | 65536 | 2386040 | 44254270 | 17762989 | 17762989 | 7.445 |
| 64 | Owner alias | 4096 | 586511 | 1455678 | 587181 | 587181 | 1.001 |
| 128 | Owner alias | 4096 | 1151759 | 2766910 | 1112749 | 1112749 | 0.966 |

The small-batch advantage does not establish superiority: original G pays a
fixed 16-MiB hot-cache load/store footprint, which amortizes as batches grow.
This candidate instead pays one 64-B read and one 64-B write per hot update.
Parallel owners hide waits only when keys distribute across owners. In the
same-segment and owner-alias cases, they correctly provide no additional
speedup over parallel search alone. The repeated-cold case is unchanged from
parallel search as well. These observations support the mechanism without
claiming that every residual cycle has been separately attributed.

## Resources And Hardware Limits

The two hot CUs now each have sixteen owner states instead of one. Each owner
has a 64-B segment-result buffer, one active update packet and a FIFO of eight
located packets, plus transaction/phase/degree bookkeeping. Segment-result
storage totals 2048 B across hot CUs; this is transient processing storage,
not a reusable segment cache. Shared AXI masters, bank credits, search
contexts and all cold processors are unchanged. The resource table is a
logical model description, **not** a synthesized LUT/BRAM/URAM estimate.

The simulator preserves the existing assumption that segment arithmetic is
committed on read response without a new multi-cycle processing pipeline.
Arbiter delay, achieved issue rate and the new hot processor's clock remain
unverified in HLS/RTL. No new hot-owner HLS prototype was compiled in this
checkpoint. The earlier search-only prototypes still miss their requested
5-ns estimated clock (8.036 ns best), so 200-MHz predictions are conditional
architecture results, not achieved hardware timing.

This candidate requires the explicit parallel-search single full-word
destination window and shared metadata master. It is rejected with the
default search path. It is not wired into production SST profiles or the
23-channel sharded hardware path. Restoring a bounded hot cache or changing
hazard forwarding would be a separate implementation, with explicit tags,
capacity, replacement, writeback and ordering costs; it cannot be assumed
free because the original has a cache.

## Verification And Evidence

- Fresh Release core: all 29 CTest tests pass, including finite owner tests.
- Focused processor tests cover same-segment order, owner aliases, reversed
  component registration, two outstanding requests, depth-one queues,
  blocked degree publication, empty input and invalid deletion. An independent
  set-based state oracle checks complete segments and exact RMW traffic.
- Fresh SST plugin builds and loads. Three four-channel memory smokes close
  their 64-request ledgers; the default native G+R SSSP smoke passes. These
  are default-path regression checks, not candidate SST timing calibration.
- All 56 focused Python tests pass. The separate historical identity suite
  still has 27 hash subassertions failing, exactly the same set as at
  `d510ea3`; these are not new numerical regression failures. Frozen manifests
  are retained unchanged, and the historical suite is not reported green.
- The [evidence guide](evidence/README.md) indexes the full matrix, earlier
  checkpoint, extraction replay and all execution stdout/stderr. The
  [verification report](verification.json) records tests and known failures.

Runtime artifacts are retained under
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-hot-lanes-v1/`.
Matrix execution is sequential, pinned to CPU 127, bounded to 4 GiB per
process with a 24-GiB system reserve and 600-second per-step timeout. Maximum
reported single-process RSS including the harness build was 342244 KiB;
this is not a concurrent-process-tree peak. The 152-run campaign plus build
took about 398 seconds. SST built with one job and an 8-GiB process ceiling.
The separate background route keeps its own 64-GiB launch threshold and is
not a hardware test of this candidate.

## Ownership And Reproduction

- Public processor contract: `cpp/include/spine_sim/grasu_update/processor.hpp`.
- Direct RMW state machine: `cpp/src/grasu_update/direct_processor.cpp`.
- Pure shared PMA encoding helpers: `cpp/include/spine_sim/grasu_update/pma_word.hpp`.
- Composition/configuration: `GraSuNativeConfig` in `grasu.hpp`, `grasu.cpp`.
- Four-arm harness: `cpp/tests/evaluation_impact/common_g/execution.cpp`.
- Preparation, execution, analysis and packaging: the Python `common_g/hot_lanes/` package.
- Focused tests: `cpp/tests/grasu_direct_processor_tests.cpp`, `tests/test_grasu_hot_lanes.py`.

```bash
cmake -S . -B /path/to/fresh-core -DCMAKE_BUILD_TYPE=Release
cmake --build /path/to/fresh-core -j2
ctest --test-dir /path/to/fresh-core --output-on-failure -j1

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.hot_lanes.study \
  --output /path/to/fresh-matrix --core-build /path/to/fresh-core/cpp \
  --previous /path/to/frozen-84-row-search/results.json

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.hot_lanes.delivery \
  --output /path/to/fresh-evidence --matrix /path/to/fresh-matrix/results.json \
  --previous /path/to/frozen-84-row-search/results.json \
  --extraction /path/to/twelve-row-extraction/results.json

python3 -m unittest tests.test_grasu_hot_lanes -v

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.hot_lanes.verification \
  --base /path/to/completed-campaign --output /path/to/fresh-verification-logs
```

Use fresh output/build directories. The matrix pins source, inputs, compiled
libraries/executable, compiler/CMake versions and flags. Packaging rechecks
live pins and every complete output-state hash; committed capsule tests
validate immutable copies without requiring the machine-local artifact tree.
The verification command indexes this checkpoint's core, SST and Python
reports and compares historical hash failures against `d510ea3`. It expects
the campaign's `verification/`, `sst-verification/` and `python-verification/`
reports; it does not execute tests or establish a hardware timing match.

## Remaining Work

1. Address the large-batch and same-segment costs with an explicit feasible
   HLS design; validate search arbitration and bounded RTL feedback first.
2. Rerun the whole G matrix and real temporal workloads; obtain independent
   publication or FPGA timing evidence rather than relying on model closeness.
3. Finish R resource controls and neighboring CC/ResPR cases. The fixed warm
   Amazon SSSP R result remains within about 5% of A4 but is not a general R
   or published 11+3 reproduction.
4. Validate actual G-to-adapter/R handoff and host windows before the common
   warm Spine demo and any proposed Figure 7--11 replacement.
