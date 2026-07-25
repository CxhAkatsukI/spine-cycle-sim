# GraSU/ReGraph Weighted HLS Synthetic Matrix

Date: 2026-07-26

## Scope

This matrix tests the executable `ff13a67` weighted-PMA contract after the
single eight-vertex vertical slice. It uses the HLS-aligned full-word ABI,
delete-plus-insert lowering for weight changes, physical-update-density host
reorder, direct PMA-to-ReGraph handoff, eight compute lanes, and exactly four
host SSSP rounds.

Every case is run through SST memHierarchy and DRAMSim3. The runner compares
the output with an independent Python implementation of HLS lowering and
Dijkstra, and also checks internal/external vertex maps, physical operation
counts, fixed-round protocol counters, and memory ledgers. Any failed check
terminates the matrix.

## Coverage And Result

| Case | Tested behavior | Vertices / initial edges | Logical / physical updates | Total / update cycles | AXIS push stalls |
| --- | --- | ---: | ---: | ---: | ---: |
| `hls_insert_shortcut_v8` | insert | 8 / 4 | 1 / 1 | 166,543 / 51 | 0 |
| `hls_exact_delete_v8` | exact delete | 8 / 4 | 1 / 1 | 166,543 / 51 | 0 |
| `hls_weight_decrease_v8` | weight decrease | 8 / 4 | 1 / 2 | 166,577 / 66 | 0 |
| `hls_weight_increase_v8` | weight increase | 8 / 4 | 1 / 2 | 166,577 / 66 | 0 |
| `hls_mixed_update_v8` | mixed update | 8 / 5 | 5 / 8 | 166,622 / 127 | 0 |
| `hls_chain_exact_four_hops_v8` | fixed-round boundary | 8 / 4 | 1 / 2 | 166,579 / 66 | 0 |
| `hls_dense_fanin_v64` | dense fan-in and stream pressure | 64 / 48 | 20 / 28 | 170,179 / 384 | 32,036 |
| `hls_source_window_4096_v8194` | source-cache window boundary | 8,194 / 4,097 | 1 / 2 | 821,312 / 66 | 32,057 |
| `hls_multisegment_variants_v128` | PMA segments and encoded variants | 128 / 48 | 17 / 34 | 170,669 / 514 | 0 |
| `hls_reorder_tie_v8` | stable host reorder tie-break | 8 / 3 | 3 / 6 | 166,627 / 112 | 0 |

All 10 cases passed with zero architecture, mathematical, and aggregate
correctness mismatches. The final-profile matrix took 25.97 host seconds.

## What It Shows

The small cases cluster at 166.5K to 170.7K cycles even though their graph and
update sizes differ. Their compute time is dominated by ReGraph's fixed scan
of the 65,536-destination physical partition in four rounds. PMA update is only
51 to 514 cycles in this range. Therefore these cases do not support a claim
that update throughput determines end-to-end latency.

The 4,096-source-window boundary is structurally different. It needs another
source-cache window and rises to 821,312 cycles, 4.93 times the one-insert
baseline. Backend requests rise only 1.74 times, while active-channel DRAM
energy rises 4.20 times. This exposes additional protocol, stream, and
contention cost rather than a simple bytes-only latency law.

The dense fan-in and source-window cases each record about 32K AXIS push
stalls. This is evidence that the execution-driven model preserves finite
FIFO/stream backpressure. It is not evidence that the exact cycle count has
already been calibrated to real hardware.

The best measured update rate in this small synthetic matrix is 10.42M logical
updates/s for dense fan-in. Weight changes must also be reported as physical
PMA operations: one logical weight change becomes delete plus insert. Rates in
this document use the requested 200 MHz profile clock and are simulator
results, not routed-hardware measurements.

## Claim Boundary

This closes the broad synthetic correctness gate for the weighted HLS-aligned
GraSU/ReGraph SSSP profile. It does not close real-dataset correctness,
cycle-level hardware calibration, PageRank, sequential/random memory
classification, total energy, area/timing, dense-batch sweeps, or large-graph
runtime. Four fixed rounds also limit this profile to graphs whose tested SSSP
state converges within that window.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_grasu_hls_weighted_matrix.py \
  --no-build \
  --out-dir results/grasu_hls_weighted_matrix_profile_final_20260726
sha256sum \
  results/grasu_hls_weighted_matrix_profile_final_20260726/matrix_manifest.json \
  results/grasu_hls_weighted_matrix_profile_final_20260726/rows.csv
```

Expected hashes are pinned in
`docs/evidence/grasu_hls_weighted_matrix_20260726.json`. The raw results are
ignored by Git; the summary, fixture generator, tests, profile, and capability
catalog are tracked.
