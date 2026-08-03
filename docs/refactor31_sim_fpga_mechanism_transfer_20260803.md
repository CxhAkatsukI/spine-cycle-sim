# Refactor31 Simulator-to-FPGA Mechanism Transfer

## Scope

This checkpoint compares the cycle simulator with the routed refactor31
reader/compute artifact at 160 MHz. It uses the exact fixture definitions from
the accepted hardware host and covers both sides of the 16,384-active-record
fallback boundary:

- exact, one destination tile;
- exact, sixteen destination tiles;
- active-gate fallback, one destination tile; and
- active-gate fallback, sixteen destination tiles.

The simulator checks final vertex state, emitted frontier, and request
completion conservation. The original FPGA logs have
`reference_validated=0`, so they are timing-stability evidence rather than
independent hardware correctness evidence.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-architecture-alignment
make -C cpp/sst -j4
python3 scripts/run_refactor31_mechanism_calibration.py \
  --out-dir docs/evidence/refactor31_sim_fpga_mechanism_transfer_v1 \
  --no-build
```

The command generates `refactor31_sim_fpga_comparison.csv`, one simulator
summary per case, and `evidence.json`.

## Uncalibrated Result

| Case | Role | Reader error | Compute error | Convergence-span error |
| --- | --- | ---: | ---: | ---: |
| exact, one tile | calibration | -79.74% | -81.05% | -80.77% |
| fallback, one tile | calibration | -68.57% | -83.82% | -70.15% |
| exact, sixteen tiles | holdout | -66.88% | -66.67% | -66.40% |
| fallback, sixteen tiles | holdout | +114.76% | +71.95% | +82.59% |

All four simulator runs have zero state/frontier mismatches and closed reader
and compute request ledgers. The cycle transfer is not accepted.

The exact reader misses approximately 8.25 million cycles in both tile shapes.
That stable absolute residual points to serialized per-active-record task
construction in the HLS schedule that the simulator currently overlaps too
aggressively. The fallback error changes sign: the old simulator fallback
repeats lookup and tile work, while refactor31 uses validation preflight plus
segmented payload execution. This is a structural model mismatch, not a fixed
launch offset.

## Back-to-Back Exact Probe

The additional `active_exact_one_tile --repeat-launches 5` run on the second
U55C is timing-stable, but all launches fail one host invariant. The harness
poisons the active bitmap before repeated launches; refactor31 exact execution
does not restore it to zero. Functional counters still report 16,384 processed
edges and 16,384 next-active vertices. The raw log is
`docs/evidence/refactor31_sim_fpga_mechanism_transfer_v1/fpga_active_exact_one_tile_repeat5.log`.

This probe is retained as a native-artifact limitation. Its rows are not
correctness-admitted and are not used to fit the simulator.

## Next Fix

1. Serialize the exact range-task control schedule per realized active record
   before the first tile can reach compute.
2. Replace the legacy fallback traversal with refactor31 preflight and bounded
   segmented payload phases.
3. Calibrate with one-tile rows and validate on sixteen-tile holdouts without
   changing parameters after seeing holdout errors.
4. Keep the paper target owner scheduler separate from this preliminary native
   artifact calibration.
