# Spine v13 PK holdout failure

## Scope

This evidence applies the immutable v13 realized-work model to the previously
unseen PK dataset. The model was frozen from AU, SU, WK, and R19 before any PK
result existed. LJ08 was deliberately not executed after PK exposed the model
failure, so it remains eligible for an independent successor-model holdout.

The simulator plugin is the immutable v12 binary:

```text
cpp/sst/build/sst-current-fpga-v12/libspine_cycle.so
sha256=f1fca617de22877ca675c72c6877444c029af8b83d4c30a25754d85f7e324b70
```

## Result

All three PK runs passed their correctness gates. All 15 available rows in the
combined calibration/PK analysis passed both structural-work and memory-ledger
validation. Timing nevertheless failed:

| Algorithm | PK total absolute error |
| --- | ---: |
| Weighted SSSP | 43.44% |
| Connected Components | 54.71% |
| Thresholded Residual PageRank | 69.13% |

For the two iterative algorithms, compute error was 13.74% for SSSP and 16.27%
for CC. Reader error was 51.90% and 66.25%, respectively, and iterative-span
error was 50.09% and 60.98%. The failure is therefore not a work-ledger or
correctness mismatch. The v13 feature form omitted reader request service,
execution-driven backpressure/component span, and the affine maintenance
control cost that becomes visible on PK.

V13 remains failed and its parameters must not be refitted. PK may be used only
as development/calibration data for a new version that is frozen before running
SO, LJ, or LJ08.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3
python3 scripts/analyze_current_fpga_spine_realized_work_v13.py \
  --allow-partial \
  --out-dir docs/evaluation_refresh_20260810/calibration_v13_holdout_pk_failure
```

The machine-readable evidence is in
`docs/evaluation_refresh_20260810/calibration_v13_holdout_pk_failure/`.
