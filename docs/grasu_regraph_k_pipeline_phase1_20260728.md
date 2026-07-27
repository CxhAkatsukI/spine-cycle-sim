# GraSU+ReGraph parameterized compute workers: Phase 1

## Scope

This phase replaces the simulator's single hard-coded ReGraph component chain
with a finite array of complete workers. Each worker owns its FIFO chain, AXI
ports, PMA reader, gather, merger, apply, and HBM wrapper. A work-conserving
controller assigns the next destination partition to a free worker and enforces
the existing superstep barrier.

The workers share the same execution-driven memory backend. Consequently, K=2
does not divide K=1 cycles by two: simultaneous AXI requests contend in the
normal backend arbitration and response queues, and an imbalanced final
partition leaves a real tail.

## Current boundary

Weighted SSSP supports `compute_pipelines >= 1`. Full and thresholded residual
PageRank deliberately reject `compute_pipelines > 1` in this phase. The current
PageRank reader computes dangling mass inside the first destination partition;
duplicating that reader would either duplicate global work or expose an invalid
iteration context. Phase 2 will model the HLS `regraph_pagerank_source_prepare`
stage once per iteration and reduce active/error/dangling statistics across
workers before opening PageRank K>1.

## Evidence

The pre-change binary was built in a detached worktree at commit `10187de`.
The same three partitioned tests were then run against this branch. Their full
evidence lines are identical:

| case | before cycles | after cycles | result |
| --- | ---: | ---: | --- |
| Weighted SSSP, K=1 | 10,576 | 10,576 | exact Dijkstra match |
| Full PageRank, K=1 | 8,095 | 8,095 | exact float32 oracle, rank sum 1 |
| Residual PageRank, K=1 | 155,326 | 155,326 | exact residual oracle |

For the same three-partition Weighted SSSP workload, K=2 completes in 6,891
cycles, or 1.535x faster than K=1. The controller observes two simultaneous
workers and 10,580 aggregate worker-busy cycles. All 15 partition passes and
495 row reads remain present, and the final distances still match Dijkstra.

Machine-readable evidence is in
`docs/evidence/grasu_regraph_k_pipeline_phase1_20260728.json`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
build/cycle-core/cpp/grasu_cycle_tests | grep partitioned_sssp
make -C cpp/sst -j2
python3 -m unittest \
  tests.test_architecture_profiles \
  tests.test_grasu_partitioned_dynamic_runner
```
