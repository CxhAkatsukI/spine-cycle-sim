# Refactor31 FPGA Calibration Evidence

## Scope

This evidence package parses the routed refactor31 direct-FPGA logs pinned by
`configs/evidence/spine_refactor31_routed_baseline_v1.json`. It verifies every
artifact hash before reading timing data and converts milliseconds to device
cycles at the routed 160 MHz clock.

The artifact is a mechanism-level baseline. It is not the final 150 MHz
paper-aligned implementation and it lacks the complete owner scheduler,
lossless reactivation protocol, and work-credit quiescence.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-architecture-alignment
python3 scripts/analyze_refactor31_fpga_calibration.py \
  --out-dir docs/evidence/refactor31_fpga_calibration
python3 -m unittest tests.test_refactor31_calibration -v
```

The command writes:

```text
docs/evidence/refactor31_fpga_calibration/refactor31_fpga_runs.csv
docs/evidence/refactor31_fpga_calibration/refactor31_fpga_case_summary.csv
docs/evidence/refactor31_fpga_calibration/refactor31_fpga_calibration_evidence.json
```

## Current Result

The four logs contain eight admitted timing launches:

| Case | Path | Samples | Median compute cycles | Compute CV |
|---|---:|---:|---:|---:|
| active_exact_one_tile | exact | 1 | 11,788,144 | 0.00% |
| active_exact_many_tiles | exact | 1 | 12,465,552 | 0.00% |
| active_gate_one_tile | fallback | 3 | 25,300,320 | 0.03% |
| active_gate_many_tiles | fallback | 3 | 32,607,520 | 0.17% |

The repeated fallback cases are stable. Many-tile placement adds about 0.68M
compute cycles on the exact path and 7.31M cycles on the fallback path, so the
tile distribution remains a first-order timing feature.

All eight launches report `reference_validated=0`. Consequently, the package
admits their timing and stability evidence but admits zero cases through the
final correctness-plus-five-repeat calibration gate. This distinction is
intentional and machine-readable.

## Frozen Transfer Matrix

`configs/experiments/spine_refactor31_fpga_calibration_matrix_v1.json` freezes
the next transfer experiment before fitting:

- calibration: AU, GG, and WK at 100K, 500K, 1M, and 4M edges;
- holdout: LJ at 2M edges and OR at 8M edges;
- weighted SSSP with insertion batches of eight;
- five FPGA repeats per case; and
- independent CPU Dijkstra, request conservation, and ledger closure gates.

The current micro fixture host cannot load arbitrary graph slices. These rows
remain explicitly pending until the generic correctness-gated slice host is
implemented; they must not be populated by extrapolation.
