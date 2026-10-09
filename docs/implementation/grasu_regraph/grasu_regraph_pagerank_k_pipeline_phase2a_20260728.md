# GraSU+ReGraph PageRank K-pipeline Phase 2a

## Delivered behavior

The PMA reader now consumes the prepared 32-bit source-property buffers used by
the current HLS prototype. PageRank degree reads and source mapping no longer
repeat inside every destination-partition scan. Instead, each apply worker reads
one 16-vertex degree burst with its destination-state burst, updates disjoint
rank/residual state, emits the next source payload, and reports local active,
error, and dangling statistics. The controller reduces those statistics at the
superstep barrier before releasing the next iteration.

This is an intentional timing-model correction relative to the Phase 1 K=1
identity baseline. Weighted SSSP remains cycle-identical.

## Correctness evidence

With three 16-vertex destination partitions and two physical workers:

| algorithm | cycles | key ledger | correctness |
| --- | ---: | --- | --- |
| Full PageRank | 4,174 | 9 partition apply/degree bursts | float32 oracle, rank sum 1 |
| Residual PageRank | 80,485 | 57 rounds, 171 passes, 285 active edges | float32 residual oracle |

The dynamic update-to-PageRank test also passes while poisoning the host degree
copy. Initial source preparation reads the updated degree payload from HBM state,
so correctness does not depend on a stale host mirror.

## Explicit remaining boundary

The initial HLS `regraph_pagerank_source_prepare` operation is functionally
represented, but this commit still materializes its output during simulator
construction. Its state/degree reads, duplicated source-buffer writes, pipeline,
and reduction tail are therefore not yet charged to cycles or memory traffic.
These numbers are validation evidence only and must not enter publication plots
until the execution-driven source-prepare component is added.
