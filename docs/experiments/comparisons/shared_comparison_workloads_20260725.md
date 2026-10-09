# Shared comparison workload corpus

## Status and claim boundary

This milestone freezes the inputs for a normalized, execution-driven Spine
versus GraSU/PMA-native-ReGraph comparison. The shared runner now exists and a
single filtered smoke case passes, but the complete matrix has **not** run. It
does **not** report a winner. Every selected run must pass both architectures
and both correctness oracles before aggregate timing is usable.

The authoritative manifest is
`configs/experiments/shared_comparison_workloads_20260725.json`. Every graph,
empty update, dynamic update, original-ID map, architecture profile, and raw
dataset source is hash-pinned. `--verify-only` needs only committed artifacts;
full regeneration additionally needs the three raw MatrixMarket files.

## Frozen matrix

| Category | Fixtures | Runs | Role |
|---|---:|---:|---|
| Synthetic calibration | 10 | 32 | May fit mechanism parameters |
| Synthetic holdout | 10 | 32 | Must not fit or select parameters |
| Real compact slices | 3 datasets | 9 | Shape/correctness validation only |
| Total | 23 | 73 | 69 static algorithm + 4 dynamic SSSP runs |

Every fixture runs weighted SSSP, three-iteration Full PageRank, and
thresholded residual PageRank. Four synthetic fixtures additionally exercise
incremental insertion, deletion fallback, weight-increase fallback, and a mixed
fallback. Calibration, holdout, and real-validation graph hashes are pairwise
disjoint.

The synthetic set covers chains, weighted diamonds, hot sources, hot
destinations, spread traffic, the 4095/4096/4097 tiny-edge threshold, the same
three dirty-source-window boundaries, gather-bank fan-in, PageRank dangling and
non-dangling graphs, shrinking residual frontiers, skew, and all required
dynamic SSSP paths.

## Real input provenance

The raw inputs are the copies already used by the local AE/ReGraph setup under
`/data/feiyang/AE/AE_Final/datasets`:

| Dataset | Raw edges | Raw SHA-256 | Compact vertices | Compact edges |
|---|---:|---|---:|---:|
| amazon-2008 | 5,158,388 | `a828ef78ef9af3c58f5fb9a0329b24128177087b4245b036a234df1e7181f254` | 650 | 1,280 |
| web-Google | 5,105,039 | `40196b70bb51c646e44c9c4c1fe8d301268a9334c03d152c4f6a47d425e45f00` | 3,045 | 4,096 |
| soc-flickr-und | 15,555,042 | `254e9f10b1020415b320a617cad77f2a540be4b953f7ac926836695c2862f64d` | 2,552 | 4,096 |

Extraction is deterministic: count outgoing degree, select the top 128 sources
by `(degree descending, original ID ascending)`, sort each source's unique
destinations, take edges round-robin up to 4096, compact IDs with the highest
degree source at local vertex 0, and derive a positive 16-bit weight from the
compact endpoints. The committed `*.map.csv` files preserve every local to
original ID mapping.

These are **real-edge compact slices**, not full-graph performance workloads.
Amazon has only 1,280 unique outgoing edges among its selected sources. No
whole-dataset throughput, scalability, or dense-batch claim may cite this
corpus; those experiments remain a separate deliverable.

## Comparison contract

- Both architectures consume byte-identical graph and update files.
- Weighted SSSP uses source 0, positive `uint16` weights, saturating `uint32`
  distances, and at most 256 rounds.
- Full PageRank uses damping 0.85 and exactly three iterations.
- Residual PageRank uses damping 0.85, epsilon `1e-6`, and at most 256 rounds.
- PageRank results require both a float32 architecture oracle and an independent
  float64 mathematical oracle. SSSP requires architecture-state and independent
  shortest-path agreement.
- Both normalized systems use the same 32-channel SST/DRAMSim3 HBM backend and
  the same algorithm parameters.
- The conversion-free result applies only to the normalized PMA-native ReGraph
  profile. Native GraSU plus native ReGraph must report conversion separately.
- The current normalized weighted ABI remains limited to one 65,536-vertex
  compute partition. This corpus cannot support a multi-partition weighted
  scalability claim.

Spine's accepted older native profile runs at 141 MHz; the source-following
normalized profiles run at 150 MHz. Results must report cycles and separately
labeled native/normalized times. A speedup must never silently use 141 MHz for
one system and 150 MHz for the other.

## Reproduction

Regenerate every artifact from the raw datasets:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/prepare_shared_comparison_workloads.py \
  --source-root /data/feiyang/AE/AE_Final/datasets
```

Verify only the committed, hash-pinned corpus:

```bash
python3 scripts/prepare_shared_comparison_workloads.py --verify-only
python3 -m unittest tests.test_shared_comparison_workloads
python3 -m unittest discover -s tests
```

The complete flow and claim boundary are summarized in
`docs/figures/shared_comparison_workloads.svg`.

The dual-oracle execution runner and its current smoke evidence are documented
in `docs/shared_comparison_runner_20260725.md`.
