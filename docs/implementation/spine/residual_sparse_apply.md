# Tile-Local Sparse Residual Apply

## Scope

`SpineResidualApplyMode::kDirtyBitmap` is an opt-in simulator architecture
candidate. The default remains `kDense`, matching the preceding implementation.
This change does not modify the HLS repository or establish routed hardware
timing. Full PageRank and connected components are unchanged.

## Invariant And Selection

At the start of a residual round, the frontier must contain all vertices above
the configured residual activation threshold. SourceMap consumes those
residuals and clears them. After that, a vertex absent from the destination
stream can only change through the global dangling share. Therefore:

- When the actual dangling share is zero, Apply visits only destinations
  marked by completed edge reductions, not every vertex in the graph.
- Every destination is marked even when signed contributions cancel. Selection
  does not depend on a host-computed list or the numerical reduced value.
- When the dangling share is nonzero, Apply visits every vertex, including
  tiles absent from the edge stream. The optimization cannot discard a small
  nonzero share just because it is below the activation threshold.

The FP32 algorithm pipeline, threshold, source clearing, resident seed state,
owner scheduling, and convergence rule are unchanged. Skipping Apply work does
not guarantee bitwise equivalence: different memory completion and frontier
orders can change FP32 accumulation. The real-input follow-up checks full rank
words, complete per-round frontier vertex sets, and finite converged residuals
against the dense control and an independent PageRank oracle. Frontier order
differences and residual word differences are reported, not discarded.

The first real-input comparison failed strict residual-word equality on
Flickr: 186 words differed, with maximum absolute difference about 1.14e-13;
the ranks were bitwise identical. The follow-up therefore uses an explicitly
post-hoc diagnostic bound of `4 * 2^-23 * epsilon` on residual differences,
in addition to requiring both complete residual arrays to satisfy the original
activation threshold. This bound changes neither arm's convergence rule. The
initial evidence is retained; the numerical result is not described as full
bitwise state equivalence, and accumulation-order causality is not established
merely by observing a small difference.

## Finite Resources And Timing

The selector owns one bitmap for the current destination tile. A 65,536-vertex
tile needs 8 KiB of bitmap RAM, not a graph-wide bitmap or unbounded work list.
The last tile uses its actual vertex count.

1. Before accepting the tile's edges, clear one 64-bit bitmap word per cycle.
2. Mark one destination per completed edge reduction. The model assumes a
   forwarded 1R/1W bitmap update accepting one mark per cycle, overlapping
   the existing single-result reduction path. Duplicate marks coalesce.
3. During Apply, load one bitmap word per cycle, then select at most one set
   bit per cycle. Enumeration is in increasing local vertex order. Reads and
   selection are separate cycles; bitmap reads may overlap outstanding AXI.
4. Each selected vertex still uses the original bounded AXI read, Apply
   pipeline, residual write, and owner/publication handshake. No HBM latency
   coefficient or G+R timing parameter is changed.

`apply_bitmap_clear_cycles`, `apply_bitmap_read_cycles`, `apply_bitmap_marks`,
`apply_bitmap_storage_bytes`, `sparse_vertices_applied`, and
`dense_fallback_tiles` expose the work. Bitmap RAM access energy and placement,
priority-encoder timing, and achievable frequency are not hardware-validated
by this simulator experiment.

## Code And Tests

- `cpp/include/spine_sim/spine_residual_apply.hpp` and
  `cpp/src/spine_residual_apply.cpp` own only bitmap selection.
- `SpineSplitPageRankCompute` schedules the explicit clear/read cycles and
  preserves dense fallback in its existing tile/owner state machine.
- `cpp/tests/spine_residual_apply_tests.cpp` compares dense and sparse runs,
  including frontier trajectories, final rank/residual words, signed
  cancellation, below-threshold untouched residuals, empty frontiers,
  dangling fallback, tail bits, stale-bit clearing, and registration order.

The evidence and before/after comparison belong in the experiment collection,
not in the paper or a previously frozen handoff.
