# CC and residual PageRank execution contract

## Scope

This document freezes the implementation and evaluation contract for the next
Delta.hls simulator milestone.  It prevents algorithm semantics, architecture
parallelism, or accuracy thresholds from changing after performance results are
visible.

## Residual PageRank

The publication mode is the sink-free, warm-repair contract from the Delta.hls
draft.  It is distinct from the existing generic cold/dangling mode.

- The accepted graph has positive out-degree at every vertex.
- A batch that creates a sink is rejected before topology publication.
- Execution starts from the previous accepted version's converged rank vector.
- Touched source rows produce a signed `new_contribution - old_contribution`
  seed after the topology switch.
- A vertex is active exactly when `abs(residual) > epsilon`.
- Successful completion requires a global drain and
  `max(abs(residual)) <= epsilon`.
- The primary threshold is frozen at `epsilon = 1e-6`.
- Sensitivity points are `1e-7`, `1e-6`, and `1e-5`; they use identical inputs,
  seeds, numerical formats, and stopping rules on both architectures.
- Every admitted performance row must pass the float32 architecture oracle and
  an independent high-precision mathematical oracle.  Residual L-infinity,
  rank error, and top-k overlap are reported with timing.

The current `epsilon / N`, dangling redistribution, cold-start execution remains
available under an explicit legacy/generic contract ID.  Its long AskUbuntu
runs are conservative stress tests and are not publication-mode residual
PageRank results.

Primary real-graph coverage uses a naturally sink-free reciprocal graph such as
`soc-flickr-und`.  AskUbuntu is a cross-check after deterministic minimum edge
closure: each sink receives one edge to its lowest-ID predecessor.  The number
and identity of closure edges are recorded.  Self-loop closure alone is not a
primary workload.

## Connected components

`connected_components` means weakly connected components with minimum vertex ID
as the component label.  It is not ReGraph's existing closeness-centrality
application.

- One logical undirected edge is represented by the atomic reciprocal pair
  `(u, v)` and `(v, u)`.
- One-sided updates are rejected.
- Initial state is `label[v] = v`.
- Map propagates the source label, Reduce computes unsigned minimum, and Apply
  activates a vertex only on strict label decrease.
- Reciprocal insertion uses incremental repair from the previous accepted label
  state.
- Any effective reciprocal deletion resets all labels to vertex IDs, activates
  the complete vertex set, and recomputes to quiescence.
- Self-loops do not change labels.  A zero-net reduced batch does not publish a
  new analytic version or execute repair.
- Correctness is checked against an independent CPU union-find/BFS oracle and a
  fixed-width architecture oracle.

The formal workload classes are same-component no-op, small-component merge,
small-to-large merge, large-component merge, hub bridge, reciprocal deletion,
and zero-net batch.  Insertion batches cover 1, 8, 64, and 4096 logical
mutations; deletion fallback covers at least 8 and 64.

## GraSU plus ReGraph parallelism

`K` denotes compute workers, not destination partitions.

- `K=1` exposes multiple logical destination partitions but executes their work
  through one complete worker.  It remains the routed implementation anchor.
- Existing direct-replication `K=4` is a simulator scalability upper bound.  It
  replicates complete workers and exceeds the U55C HMSS AXI-master budget, so it
  is not the publication baseline.
- The competitive target is shared-K4: four scatter/gather workers share the
  HBM wrapper, merger, apply path, and vertex state, matching the organization
  supported by the original ReGraph source.
- shared-K4 requires work-conservation checks, finite arbitration/backpressure,
  and a separately synthesized shared-port HLS top before it is called routed.

For an early K1 comparison, define

```
S1 = T(GraSU+ReGraph, K1) / T(Spine).
```

Under identical work and clock, four workers provide at most fourfold ideal
worker scaling, so `S1 > 4` is a sufficient early screen that Spine remains
faster than an ideal same-work K4 (`S4 >= S1 / 4 > 1`).  This bound does not
replace direct-K4 and shared-K4 publication results.  Rows that change physical
work, omit shared contention, or use different algorithm semantics cannot use
the bound.

## Execution and admission

K1 correctness and timing run first for both new algorithms.  Direct-K4 and
shared-K4 follow without changing the frozen workload or algorithm parameters.
Independent simulator jobs may run concurrently while host available memory
stays above 8 GiB; no swap is configured on the current host.  Long synthesis
and simulator jobs run in the background and do not block implementation.

Every formal result records source revision, profile hash, workload hash, SST
plugin hash, algorithm contract ID, threshold, worker topology, request/byte
conservation, correctness status, and wall-clock runtime.  Failed correctness or
conservation rows are excluded from all performance aggregates.
