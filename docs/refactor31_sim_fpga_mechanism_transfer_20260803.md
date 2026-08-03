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

## Evidence Boundary

This evidence supports refactor31-native weighted SSSP mechanism transfer. It
does not support hardware correctness admission for the original timing-only
logs, real-slice transfer, owner-scheduler FPGA calibration, or hardware
performance claims for CC/PageRank policy kernels. The paper-target owner
scheduler is intentionally separate from this routed native baseline.

The remaining timing work is to explain the multi-tile segmented-fallback
residual with HLS schedule/RTL evidence and then freeze the native profile
before running medium real-slice calibration and holdout workloads.
