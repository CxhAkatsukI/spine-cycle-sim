# Refactor31 Simulator-to-FPGA Mechanism Transfer

## Scope

This checkpoint compares the cycle simulator with the routed refactor31 SSSP
reader/compute artifact at 160 MHz. It uses the exact fixture definitions from
the accepted hardware host and covers both sides of the 16,384-active-record
fallback boundary:

- exact, one destination tile;
- exact, sixteen destination tiles;
- active-gate fallback, one destination tile; and
- active-gate fallback, sixteen destination tiles.

Only the two one-tile rows are calibration inputs. The two sixteen-tile rows
are immutable holdouts. The simulator checks final vertex state, emitted
frontier, and request completion conservation. The original FPGA logs have
`reference_validated=0`, so they are timing-stability evidence rather than
independent hardware correctness evidence.

## Modeled Native Mechanisms

The refactor31 profile now includes the serialized per-active-record range-task
control schedule and segmented fallback setup. The fitted one-tile constants
are:

```text
reader active-record control: 520 cycles/record
segmented fallback setup:      3,185,887 cycles
```

Fallback emits an explicit defer-active marker. Compute then executes the HLS
bitmap protocol rather than publishing a Python frontier directly:

1. clear the graph-domain active bitmap;
2. read/modify/write changed tile words;
3. sweep 128 words per chunk with read II=4;
4. scan set bits with bit II=2;
5. read each published vertex value and write the active-output record; and
6. clear the bitmap again after publication.

All accesses use the existing finite AXI/HBM ports and therefore remain
subject to request windows, arbitration, response queues, and backpressure.

## Result

| Case | Role | Reader error | Paired launch-to-finish error |
| --- | --- | ---: | ---: |
| exact, one tile | calibration | +0.075% | -10.595% |
| fallback, one tile | calibration | -0.001% | -5.981% |
| exact, sixteen tiles | holdout | +0.283% | -0.042% |
| fallback, sixteen tiles | holdout | -11.302% | -17.992% |

All four simulator runs have zero state/frontier mismatches and closed reader
and compute request ledgers. The exact-path transfer is accepted on both tile
shapes. The fallback one-tile calibration is also within the gate. The
multi-tile fallback is the remaining native timing gap: it is below the 20%
component gate but exceeds the 15% total-cycle target. It must not be described
as cycle-matched.

`compute_active_cycles` remains an internal first-compute-word diagnostic. The
FPGA `compute_ms`/`conv_ms` timer starts at the paired CU launch, so the
comparison uses Reader launch to compute completion. Comparing FPGA launch
time to the simulator's first compute word would incorrectly omit serialized
Reader work.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-architecture-alignment
make -C cpp/sst -j4
python3 scripts/run_refactor31_mechanism_calibration.py \
  --out-dir docs/evidence/refactor31_sim_fpga_mechanism_transfer_v2 \
  --no-build
```

The command generates `refactor31_sim_fpga_comparison.csv`, one simulator
summary per case, and `evidence.json`. The manifest binds the architecture
profile, relevant simulator sources, and the loaded SST shared library by
SHA-256.

## Frozen Real-Slice Transfer Gate

The subsequent real-slice matrix uses 14 correctness-gated weighted-SSSP
cases from Amazon-2008, web-Google, wiki-topcats, LiveJournal, and Orkut. The
12 AU/GG/WK cases at 100K, 500K, 1M, and 4M edges are calibration inputs. The
2M-edge LiveJournal and 4M-edge Orkut cases are immutable holdouts. Every FPGA
row has five board samples; every simulator row must match the FPGA round,
resident-level, and processed-edge ledgers and independently pass final-state,
frontier, and request-conservation checks.

The residual model was frozen before the holdout was revealed:

```text
calibrated cycles = raw simulator cycles
                  + fixed
                  + rounds * c_round
                  + processed edges * c_edge
```

Non-negative, relative-error-weighted least squares is fitted only on the 12
calibration rows. The pre-registered holdout gate then produces:

| Role | Cases | Paired median error | Paired max error | Reader median error | Compute median error | Paired Spearman |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| calibration | 12 | 19.93% | 57.41% | 18.04% | 19.93% | 0.993 |
| frozen holdout | 2 | 10.85% | 12.04% | 9.52% | 10.85% | 1.000 |

The frozen holdout is admitted: its paired median is below 15%, paired maximum
is below 30%, component medians are below 20%, and rank correlation exceeds
0.9. This is evidence of transfer to the two unseen real-slice workloads, not
a claim of uniform pointwise matching. In particular, the fitted model has a
57.41% worst calibration-row error and should not be described as matching
every scale or topology.

The two longest simulator rows also expose the current fidelity/runtime
tradeoff. AU-4M executes 48 rounds and 22,002,549 propagated edges in
10,235,422,862 modeled cycles, taking 104,776 seconds of host wall time.
GG-4M executes 49 rounds and 15,500,240 propagated edges in 8,620,217,846
modeled cycles, taking 89,305 seconds. The detailed SST path is therefore a
transfer-validation tool, not yet a practical full-graph campaign engine.

Reproduce the fail-closed analysis after all 14 summaries exist with:

```bash
cd /home/chuxiao/spine-cycle-sim-architecture-alignment
python3 scripts/analyze_refactor31_real_slice_transfer.py \
  --fpga-root /data/feiyang/codex_builds/spine_paper_alignment/refactor31_transfer_matrix_fpga_v2 \
  --sim-root /data/feiyang/codex_builds/spine_paper_alignment/refactor31_transfer_complete_sim_v3 \
  --out-dir /data/feiyang/codex_builds/spine_paper_alignment/refactor31_transfer_evidence_v3
```

The hash-bound outputs are archived in
`docs/evidence/refactor31_real_slice_transfer_v3/`. The analyzer exits nonzero
if any frozen holdout condition fails.

## Evidence Boundary

The micro evidence supports refactor31-native weighted-SSSP mechanism transfer
but does not independently admit hardware correctness for the original
timing-only micro logs. The real-slice matrix adds independent CPU-Dijkstra
correctness, request-ledger closure, and an admitted frozen holdout for the
resident Reader/Compute event window.

Neither layer calibrates the paper-target owner scheduler, graph load,
maintenance, host orchestration, or CC/PageRank policy cycles. The paper-owner
scheduler remains a separate functionally validated and routed feasibility
artifact. The multi-tile segmented-fallback micro residual also remains an
explicit native timing gap rather than being erased by the aggregate
real-slice fit.
