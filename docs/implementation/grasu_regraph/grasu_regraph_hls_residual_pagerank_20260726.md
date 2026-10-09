# Proposed HLS-equivalent GraSU + ReGraph residual PageRank

## Scope and claim

This milestone connects thresholded signed-residual PageRank to the same
ff13a67 full-word PMA and host reorder used by the weighted SSSP and Full
PageRank profiles. The result is an execution-driven SST-HBM simulation of a
proposed HLS-equivalent design. No residual-PageRank xclbin or timing closure is
claimed.

The profile
`configs/architectures/grasu_regraph_weighted_pma_hls_proposed_residual_pagerank_ff13a67.json`
uses eight map/reduce lanes, a 32-entry adapter AXIS FIFO, timed degree RMW, and
a packed 64-bit state per vertex: one float32 rank and one float32 residual.

## Execution and correctness

The device window is serial:

1. lower logical weight replacements and apply the ff13a67 host reorder;
2. execute full-word PMA updates and out-degree RMW operations;
3. wait for the degree/PMA/AXI/HBM completion barrier;
4. execute signed-residual ReGraph rounds until the threshold is met or the
   256-round limit is reached.

Every run checks the final PMA and HBM degree state, the float32 architecture
oracle, a 200-iteration float64 Full PageRank oracle, external vertex order,
the residual norm, active-edge count, frontier trace, and the complete backend
request ledger.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
make -C cpp/sst -j2
python3 scripts/run_sst_grasu_regraph_hls_residual_pagerank.py \
  --out-dir results/grasu_hls_residual_pagerank_smoke_20260726 \
  --no-build
```

| Metric | Value |
|---|---:|
| Total cycles | 2,831,244 |
| Update cycles | 201 |
| Compute cycles | 2,831,043 |
| Converged iterations | 82 |
| Active edges processed | 374 |
| Final residual L1 | 5.3386e-7 |
| Backend requests | 2,772,632 |
| Correctness/state mismatches | 0 |
| SST host wall time | 36.60 s |

The first 71 rounds keep all eight vertices active; later rounds shrink to
frontiers of one to six vertices and eventually zero. Runtime does not shrink
proportionally because each round still performs the fixed 65,536-destination
gather/apply sweep.

The 8-byte state also changes the AXI ledger: one 16-vertex rank/residual burst
is 128 bytes and becomes two 64-byte backend requests. Treating one logical
state operation as one request undercounted this smoke by 1,343,488 requests;
the final ledger derives request beats from state width and closes exactly.

## Remaining limitations

- The residual policy, packed state path, and degree RMW CU are unsynthesized.
- Requested 200 MHz and source-map latency are structural profile values.
- Only a dynamic smoke is frozen here. Real compact/full datasets, dense batch
  behavior, comparison against Spine, energy attribution, and PPA remain later
  acceptance gates.
- One 19-bit destination partition and 4096 physical updates per batch are the
  current proposed-profile limits.
