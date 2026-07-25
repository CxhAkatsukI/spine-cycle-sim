# Proposed HLS-equivalent GraSU + ReGraph Full PageRank

## Scope and claim

This milestone connects Full PageRank to the ff13a67 weighted-PMA foundation.
It is an execution-driven SST-HBM simulation of a proposed HLS-equivalent
variant, not evidence that a PageRank xclbin exists or closes timing at 200 MHz.

The frozen profile is
`configs/architectures/grasu_regraph_weighted_pma_hls_proposed_pagerank_ff13a67.json`.
It preserves the ff13a67 full-word PMA ABI, physical-update-density host vertex
reorder, four GraSU PMA channels, eight ReGraph map/reduce lanes, a 32-entry
adapter AXIS FIFO, 16 outstanding requests per port, and the requested 200 MHz
kernel clock. It adds one proposed degree RMW path with a finite 4096-entry
ordered completion scoreboard.

## Measured execution window

The simulator executes these stages serially:

1. Lower logical weight changes to exact delete-old and insert-new records.
2. Reorder vertices by physical update density and build the full-word PMA.
3. Run GraSU PMA update and timed out-degree read/modify/write operations.
4. Wait for PMA, degree, AXI, and HBM completion.
5. Stream the PMA directly into ReGraph and execute three Full PageRank
   iterations with explicit degree reads and rank-state traffic.

There is no PMA-to-edge-array conversion stage. Host preprocessing remains
outside the timed device window, matching the ff13a67 SSSP profile contract.

## Correctness gates

The SST component fails closed unless all of the following hold:

- the final PMA edge set equals the materialized dynamic snapshot;
- the HBM degree array equals the final out-degree vector;
- float32 architecture ranks match the independent in-component float32 oracle;
- ranks match an independent float64 fixed-iteration oracle within `1e-5`;
- ranks are mapped back to external vertex order and match the Python float64
  oracle;
- update, degree, compute, and backend request ledgers close exactly.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
make -C cpp/sst -j2
python3 scripts/run_sst_grasu_regraph_hls_pagerank.py \
  --out-dir results/grasu_hls_pagerank_smoke_20260726 \
  --no-build
```

The frozen dynamic smoke uses 8 vertices. Five logical updates become eight
physical full-word PMA operations because weight replacements are lowered to
delete plus insert.

| Metric | Value |
|---|---:|
| Total cycles | 133,116 |
| Update cycles | 201 |
| Compute cycles | 132,915 |
| PageRank iterations | 3 |
| Degree reads/writes during update | 8 / 8 |
| Backend requests | 50,796 |
| Correctness mismatches | 0 |
| PMA state mismatches | 0 |
| Degree state mismatches | 0 |
| SST host wall time | 1.57 s |

The fixed 65,536-destination PageRank sweeps dominate this tiny graph. This is
expected ReGraph behavior and is an important small-batch comparison cost, not
a simulator shortcut.

## Remaining limitations

- No PageRank HLS kernel has been synthesized, compiled, or run in hw_emu/hw.
- The 200 MHz clock and source-map latency are proposed parameters, not timing
  closure evidence.
- This milestone validates one dynamic smoke. The three-dataset compact matrix,
  full datasets, dense batches, energy attribution, and PPA remain later gates.
- The profile supports one 19-bit destination partition. The existing
  partitioned normalized profile remains a separate architecture proposal.
