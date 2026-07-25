# Spine Dynamic PageRank Measurement Contract

## Scope

Spine Full PageRank and thresholded residual PageRank now support the same
small-batch execution contract as the proposed HLS-equivalent GraSU/ReGraph
profiles:

1. Preload an initial graph snapshot outside the timed device window.
2. Execute only the supplied differential update through the existing timed
   Spine L0 maintenance pipeline.
3. Wait for maintenance and its AXI/HBM traffic to drain.
4. Read the materialized final level state and execute PageRank through the
   existing Reader, AXIS FIFOs, map/reduce pipeline, and SST-HBM backend.

The implementation does not mutate the final graph in Python. The initial
snapshot is materialized as an L0 `SpineL0State`; insertion and deletion
records still pass through `SpineL0Maintenance`, including sorted-edge scans,
target-level selection, carry merge, and persistent writes. Active bins,
out-degrees, and both correctness oracles are derived independently from the
final snapshot.

## Compact-state limitation

The zero-time preload currently represents the initial compact graph as one
L0 batch. This is a valid state produced by inserting the compact graph in one
batch, and the next update therefore carries L0 into L1. It is not yet a
general loader for arbitrary multi-level full-dataset checkpoints. Inputs that
exceed the configured L0 family capacity fail closed.

## Correctness gates

The dynamic path fails unless:

- initial and update slices use the same nonzero vertex count;
- the update is nonempty and materializes a nonempty graph;
- maintenance persists exactly the final graph edge count;
- host differential coverage matches the update source set;
- float32 architecture results and float64 mathematical results both match;
- AXI requests and DRAM requests close exactly.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --out-dir results/spine_hls_full_pagerank_dynamic_smoke_20260726 \
  --scenario full_pagerank \
  --validation-mode generic \
  --workload tests/data/shared_comparison/real_amazon_2008_compact.slice \
  --update-workload tests/data/hls_weighted_real_batches/real_amazon_2008_insert_u8.slice \
  --pagerank-iterations 3 \
  --pagerank-damping 0.85 \
  --max-cycles 30000000 \
  --no-build
```

## Frozen smoke result

The Amazon-2008 compact insert case preloads 1,280 initial edges and times an
8-edge insertion batch. Maintenance persists 1,288 final edges before three
Full PageRank iterations.

| Metric | Value |
|---|---:|
| Total cycles at 141 MHz | 137,280 |
| Maintenance cycles | 27,504 |
| Backend requests | 22,793 |
| DRAM reads / writes | 18,986 / 3,807 |
| DRAM activates / precharges | 1,710 / 1,708 |
| Architecture mismatches | 0 |
| Mathematical mismatches | 0 |
| Maximum float32 error | 9.31323e-10 |
| SST host wall time | 2.144 s |

This smoke closes the dynamic execution semantics, not the final comparative
performance claim. The common nine-case Spine/GraSU Full PageRank matrix is the
next gate.
