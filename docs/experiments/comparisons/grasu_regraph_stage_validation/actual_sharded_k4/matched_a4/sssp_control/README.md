# Weighted SSSP Four-Little Correctness Control

## Question And Scope

Can the independent four-Little path and the actual routed-K4 model execute
the same weighted-SSSP arithmetic and produce the same complete resident
one-round state? This is a prerequisite for a same-algorithm comparison;
the previous fixed-point PR A4 control must not be timed against production
weighted SSSP and called an integration overhead.

This is an optional **local UDF extension**, not an original-publication
workload. The inspected pristine author artifact supplies PR/BFS/CC UDFs.
The separately pinned local HLS SSSP UDF is
`/home/chuxiao/regraph/ReGraph/acc_udfs/sssp/l2.h`; its path and SHA-256 are
recorded in [the results manifest](evidence/results.json).

## What Is Checked

| Gate | Meaning |
| --- | --- |
| UDF/source comparison | Scatter, min reduction and Apply match the pinned local HLS UDF over deterministic boundary and random inputs. This is numerical equivalence, not HLS timing. |
| Four-Little Gather | All 65,536 gathered values, registration order, restart and bounded output pressure. |
| Memory/frontend | Weighted packets survive edge reads, source-window service, Scatter, Gather and both merge levels; request/byte/terminal conservation is checked. |
| SSSP Apply | Finite old-state reads, strict improvement, stale-active clearing, reordered responses, credits, terminators, restart and four acknowledged output replicas. |
| Composed resident round | Cold-source, warm-active and inactive fixtures each compare all 65,536 padded words in all four A4 replicas against an independent synchronous-relaxation oracle and both K4 source replicas. |
| Default preservation | Four pre-change component outputs and two complete original-source comparisons must remain byte-identical, including emitted cycles and counters. |

The composed graph has 129 logical vertices and nine unique directed weighted
edges, padded to one 65,536-vertex destination partition. Four compact edge
streams are source-sorted and assigned by `source % 4`. This deliberately
small functional fixture is **not** author DBG/task preparation, a large-graph
matrix, old-graph/update convergence, or a multi-partition performance test.
The K4 arm uses the explicit routed composition and checks its complete
one-round result; no fabricated FPGA result is involved.

The admitted completion boundary includes the last replica write
acknowledgement, not just Apply completion. Allocation guards and complete
padding are checked, not a sampled checksum. The inactive fixture must clear
stale activity and produce no newly active vertices.

## Timing Is Not Yet Comparable

The independent A4 control retains its declared 210-MHz mock-memory fixture
and PR-derived elastic pipeline timings. The routed K4 arm uses 150 MHz and
its declared mock-memory configuration. A4 writes four source replicas;
K4 writes two. Their topology, ports, destination work assignment and timing
assumptions are not identical. `SsspApply` explicitly labels its post-read
pipeline timing as inherited from PR, not audited against SSSP HLS.

Diagnostic cycles establish finite execution and pressure sensitivity only.
The runner requires `timing_ratio_admitted: false` for every row. It does not
compute an A4/K4 speedup, fit a timing multiplier, modify the default SST
plugin, replace the FPGA matrix, or admit a publication-performance match.

Before that comparison, the remaining gates are:

- Admit the same real graph, vertex mapping, weighted edge multiset, initial
  state and rounds/convergence in both paths, including actual task geometry.
- Audit SSSP HLS scheduling and use explicitly comparable clock, memory
  service, AXI capacities, physical port budget and resident event windows.
- Preserve and report legitimate per-design layout/state-replica differences;
  equal frontend counts alone do not mean identical resources.
- Run bounded complete-state/traffic checks before interpreting performance.
- Keep original-paper topology/platform reproduction, isolated G timing and
  actual integrated-path timing as separate acceptance decisions.

## Negative Findings

An initial frontend stress combined a depth-one source-control queue with
gapped source windows. The inherited source-request protocol could block
before draining outstanding source responses. This is not claimed fixed.
The accepted normal-depth test includes window gaps; the accepted depth-one
pressure test uses sequential windows. Future changes to that protocol need
their own default-preserving regression, not a silent timing adjustment.

The initial composed fixture also included two weights for the same ordered
vertex pair. The current PMA builder keys by destination and replaced one
weight; the complete-state oracle correctly rejected it. The corrected
fixture uses nine unique ordered pairs, the currently admitted scope.
Parallel weighted edges are not claimed supported by this test.

The failed attempts remain under
`/data/chuxiao/experiments/original_a4_sssp_control_20261011/first_tests/`,
`diagnostic/` and `composed_smoke/`. They are not passing matrix rows and are
not overwritten by the fresh delivery run.

## Owners And Reproduction

Arithmetic is in `cpp/include/spine_sim/original_regraph/udf.hpp`.
Finite old-state Apply is separately owned by `sssp_apply.hpp/.cpp`.
The composed fixture/wiring live in `cpp/tests/original_regraph/sssp/`;
existing reader/Scatter/Gather/merge interfaces default to unchanged PR.
No source list in the production SST plugin changes.

Configure an isolated build, then run the bounded evidence gate:

```bash
cmake -S . -B build/original-a4-sssp-review \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
  -DSPINE_SSSP_UDF_REFERENCE=/home/chuxiao/regraph/ReGraph/acc_udfs/sssp/l2.h
python3 -m spine_cycle_sim.experiments.original_regraph_execution.sssp_control \
  --build build/original-a4-sssp-review \
  --baseline /data/chuxiao/experiments/original_a4_sssp_control_20261011/baseline \
  --hls-udf /home/chuxiao/regraph/ReGraph/acc_udfs/sssp/l2.h \
  --output results/original_a4_sssp_fresh
```

The runner refuses existing output paths, uses two build workers, bounds each
child to 8 GiB, preserves 16 GiB available-memory reserve, and records timeout,
RSS, compiler/cache, affinity, source/reference/binary identities and raw
stdout/stderr. Full baseline/source-capture comparisons require the indexed
local historical captures. Without those files the runner fails rather than
claiming full regression. Dependency-free arithmetic/frontend/round tests
remain available through CTest; the external source comparison is opt-in.

Read [results.json](evidence/results.json) for the acceptance decision and
`evidence/raw/` for individual commands, outputs and resource records. A
successful correctness gate is not completion of the broader performance goal.

## Verification

The isolated Release build passed all 28 CTest cases. Python regression passed
87 original-ReGraph tests, 161 sharded-K4 tests and 15 repository-structure
tests. Document-layout and generated-catalog checks also passed. Commands,
stdout/stderr and resource records are under `verification/`.

The first sharded-K4 Python invocation failed before a watchdog child could
start: the outer runner imposed an 8-GiB address-space hard limit, while that
test's nested watchdog requests a 64-GiB address-space limit. The saved
`python_1.*` records show this verification-wrapper conflict. The unchanged
suite then passed under the existing process-tree watchdog, which enforced
an 8-GiB simultaneous RSS budget and a 16-GiB available-memory reserve;
see `python_sharded_tree_watchdog.*`. No production limit or test assertion
was weakened to obtain that pass.
