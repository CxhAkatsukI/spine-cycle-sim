# D-stage Phase 4B Component Timing Model

Date: 2026-07-20

## Scope

Phase 4B builds an interpretable D-stage timing layer for the current hardware
behavior.

Confirmed boundary:

- D-stage only.
- No HLS kernel change.
- No xclbin rebuild.
- Uses the frozen Phase 3C model as the baseline current-hardware timing model.
- Adds nonnegative correction components that map to observed hardware actions.
- Preserves Phase 3B/3C synthetic trust while improving Phase 4A exact real
  slice outliers.
- What-if results are analysis-level estimates, not implemented RTL/HLS changes.

This phase is intentionally not a full replacement of the Phase 3C model. A pure
nonnegative component replacement improved some exact real slices but destroyed
synthetic validation: phase3c holdout reached 27.85% median / 124.41% max error,
phase3c final reached 28.26% median / 74.35% max error, and synthetic
calibration reached 20.21% median / 76.05% max error. That failed the goal of
preserving the already trusted synthetic model.

## Model Shape

The implemented model is:

```text
predicted_cycles =
  Phase3C_base_current_hw(row)
  + clipped_range_stream_correction
  + mixed_full_peak_range_correction
  + fallback_clipped_stream_correction
```

The correction coefficients are fit with nonnegative coordinate descent on the
residual between hardware cycles and the Phase 3C base prediction.

Correction components:

- `clipped_range_stream_correction`: cost per clipped destination range.
- `mixed_full_peak_range_correction`: extra pressure when a case mixes fast and
  full tile paths, scaled by peak clipped ranges.
- `fallback_clipped_stream_correction`: extra pressure when fallback tiles replay
  clipped ranges.

Latest fitted coefficients:

```text
clipped_range_stream_correction   = 102.07 cycles/range
mixed_full_peak_range_correction  = 4943.84 cycles/peak mixed range
fallback_clipped_stream_correction = 116.94 cycles/(fallback tile * clipped range)
```

Interpretation:

- The Phase 3C base still carries the broad current-hardware timing behavior.
- The correction layer explains exact real-slice cases where replay, mixed
  fast/full path pressure, or fallback-path clipping create extra cycles.
- Components are nonnegative, so the model only adds missing hardware-action
  costs instead of hiding errors with subtractive black-box terms.

## Code Changes

Simulator repo:

- `scripts/analyze_dstage_component_model.py`
  - Loads Phase 3C base fit.
  - Builds calibration and holdout groups from synthetic and exact real-slice
    hardware evidence.
  - Fits nonnegative residual correction components.
  - Writes per-case component breakdown and two what-if estimates.
- `tests/test_dstage_component_model.py`
  - Covers correction feature extraction.
  - Covers trust/borderline/untrusted thresholds.
  - Covers the replay-to-clipped what-if monotonicity.

## Evidence Inputs

Base Phase 3C fit:

```bash
/home/chuxiao/spine-cycle-sim/results/phase3c_full_partition_analysis_20260719_175848/fit.json
```

Synthetic calibration inputs:

```bash
/home/chuxiao/spine-cycle-sim/results/dstage_phase3a4_replay_calibration_hw_20260719_155924
/home/chuxiao/spine-cycle-sim/results/phase3c_full_partition_calibration_hw_20260719_175201
```

Exact real-slice input:

```bash
/home/chuxiao/spine-cycle-sim/results/phase4a_amazon_exact_slices_hw_20260719_224034
```

Exact real-slice calibration cases:

```text
amazon_top512_exact
amazon_top8192_exact
amazon_densewin4096_active3933_exact
amazon_stride512_exact
```

Exact real-slice holdout cases are the other Phase 4A exact cases.

Latest output directory:

```bash
/home/chuxiao/spine-cycle-sim/results/phase4b_component_model_20260720_000027
```

Key outputs:

```bash
component_model.json
component_predictions.csv
group_summary.csv
baseline_predictions.csv
baseline_group_summary.csv
```

## Reproduction Command

```bash
cd /home/chuxiao/spine-cycle-sim
OUT=results/phase4b_component_model_$(date +%Y%m%d_%H%M%S)
python3 scripts/analyze_dstage_component_model.py --out-dir "$OUT"
```

Verification:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 -m py_compile scripts/analyze_dstage_component_model.py tests/test_dstage_component_model.py
python3 -m unittest discover -s tests
git diff --check
```

Latest verification result:

```text
Ran 45 tests in 11.558s
OK
```

## Validation Summary

Current Phase 4B model:

| group | samples | median abs error | max abs error | trusted | borderline | untrusted |
|---|---:|---:|---:|---:|---:|---:|
| phase3b_broad | 22 | 5.86% | 26.69% | 20 | 2 | 0 |
| phase3c_final | 8 | 3.79% | 26.27% | 7 | 1 | 0 |
| phase3c_holdout | 12 | 4.38% | 24.47% | 10 | 2 | 0 |
| phase4a_exact_calibration | 4 | 7.54% | 19.44% | 3 | 1 | 0 |
| phase4a_exact_holdout | 8 | 13.23% | 23.51% | 6 | 2 | 0 |
| synthetic_calibration | 54 | 4.82% | 25.41% | 53 | 1 | 0 |

Frozen Phase 3C baseline on the same groups:

| group | samples | median abs error | max abs error | trusted | borderline | untrusted |
|---|---:|---:|---:|---:|---:|---:|
| phase3b_broad | 22 | 5.28% | 17.80% | 21 | 1 | 0 |
| phase3c_final | 8 | 1.95% | 6.84% | 8 | 0 | 0 |
| phase3c_holdout | 12 | 3.55% | 18.15% | 11 | 1 | 0 |
| phase4a_exact_calibration | 4 | 26.60% | 34.00% | 1 | 1 | 2 |
| phase4a_exact_holdout | 8 | 15.88% | 36.02% | 3 | 4 | 1 |
| synthetic_calibration | 54 | 2.38% | 12.38% | 54 | 0 | 0 |

Main outcome:

- Exact real-slice calibration improved from 2 untrusted to 0 untrusted.
- Exact real-slice holdout improved from 1 untrusted to 0 untrusted.
- Synthetic groups still have 0 untrusted cases.
- Some synthetic maximum errors increased, so this is not "strictly better on
  every row." It is better for the Phase 4B objective: preserve trust while
  recovering exact real-slice outliers with interpretable hardware-action terms.

## Exact Slice Bottlenecks

Representative exact real-slice rows:

| case | role | abs error | top correction | correction share | replay what-if speedup | half full-sweep speedup |
|---|---|---:|---|---:|---:|---:|
| amazon_top512_exact | calibration | 19.44% | clipped range stream | 2.9% | 1.78x | 1.00x |
| amazon_top8192_exact | calibration | 2.70% | fallback clipped stream | 29.5% | 2.21x | 1.03x |
| amazon_densewin4096_active3933_exact | calibration | 0.75% | mixed full peak range | 33.5% | 1.63x | 1.01x |
| amazon_top4096_exact | holdout | 12.20% | mixed full peak range | 32.6% | 1.47x | 1.00x |
| amazon_densewin512_active507_exact | holdout | 21.53% | mixed full peak range | 31.1% | 1.47x | 1.04x |
| amazon_densewin8192_active7893_exact | holdout | 14.84% | fallback clipped stream | 24.9% | 2.23x | 1.03x |
| amazon_stride4096_exact | holdout | 13.95% | clipped range stream | 1.8% | 1.86x | 1.00x |

The strongest current optimization signal is replay/source-tile visit reduction.
For the large exact slices, the analysis-level replay-to-clipped what-if predicts
roughly 1.47x to 2.23x D-stage speedup. Halving the full-sweep contribution gives
only about 1.00x to 1.04x on these exact slices, so full-sweep cost alone is not
the dominant immediate optimization target for this amazon-2008 exact-slice set.

## What We Can Claim

Reasonable claims now:

- For D-stage, the simulator now has a hardware-action-aligned correction layer
  for current hardware behavior.
- The model is calibrated on real hardware evidence and validated on both
  synthetic and exact real-slice holdout groups.
- The model can identify likely D-stage bottleneck classes for the tested cases:
  clipped-range streaming, mixed fast/full pressure, and fallback clipped replay.
- The model can provide analysis-level what-if estimates for reducing replay and
  full-sweep cost.

Claims to avoid:

- Do not claim full AXI/HBM cycle accuracy.
- Do not claim this replaces detailed stream/backpressure modeling.
- Do not claim end-to-end graph application timing; this is D-stage only.
- Do not use B-stage scan/filter/write optimization estimates yet; that belongs
  to Phase 4C.
- Do not claim the what-if speedups are achieved by implemented hardware changes.

## Next Step

Phase 4C should add the B-stage current-hardware scan/filter/write timing model.
That will let us evaluate maintenance-side optimizations such as reducing
multi-pass sorted-edge scans, improving partition/family filtering, or changing
write staging. Once B-stage and D-stage are both decomposed, the simulator can
produce a more complete per-stage bottleneck report for current Spine hardware.
