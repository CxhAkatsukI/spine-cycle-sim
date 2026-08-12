# Spine current-FPGA v14 SO failure and v15 freeze

## Scope

This evidence closes the v14 SO transfer attempt without changing the frozen
v14 parameters, then freezes the v15 HLS-mechanism timing model before any
current-plugin LJ or LJ08 result exists.

The immutable simulator plugin is:

```text
cpp/sst/build/sst-current-fpga-v12/libspine_cycle.so
sha256 f1fca617de22877ca675c72c6877444c029af8b83d4c30a25754d85f7e324b70
```

## V14 failure

All three SO executions pass their algorithm oracle, structural-work checks,
and memory-ledger checks. The frozen v14 timing model nevertheless fails to
transfer:

| Algorithm | Total absolute error | Dominant component error |
|---|---:|---:|
| Weighted SSSP | 48.96% | reader 49.52%, compute 75.90% |
| Connected Components | 32.98% | reader 33.52%, compute 20.98% |
| Thresholded Residual PageRank | 4.72% | maintenance 4.72% |

The failure package is in
`docs/evaluation_refresh_20260810/calibration_v14_holdout_so_failure/`.
It is intentionally marked incomplete because LJ and LJ08 were withheld once
SO had already disproved the v14 timing claim.

Reproduce the analysis with:

```bash
python3 scripts/analyze_current_fpga_spine_component_features_v14.py \
  --allow-partial \
  --holdout-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v14_20260812 \
  --out-dir /tmp/spine-v14-so-failure
```

## Root cause

V14 adds a fitted parent-request cost to execution-driven component cycles.
Those component cycles already contain AXI service, finite FIFO/AXIS
backpressure, response timing, and pipeline stalls. The combination therefore
double counts request service when extrapolating beyond the development range.

V15 uses non-overlapping mechanism terms:

- reader: routed launches, vertex-domain publication work, and completed
  reader parent requests;
- SSSP compute: one routed event launch/drain term plus the execution-driven
  compute span;
- CC compute: label-state parent requests plus execution-driven compute span
  and launches;
- ResPR: maintenance only for the observed zero-round dynamic updates;
- total: maintenance plus `max(reader, compute)` and the measured overlap
  residual, never reader plus compute.

## V15 freeze

V15 uses AU, SU, WK, R19, PK, and SO as development data. LJ and LJ08 are the
frozen current-plugin transfer set. Older-plugin results for those graph names
exist historically, so this is described as frozen transfer validation rather
than a project-lifetime blind holdout.

Before transfer execution, the development evidence is:

| Algorithm | Total LOO median | Total LOO max |
|---|---:|---:|
| Weighted SSSP | 7.67% | 9.20% |
| Connected Components | 13.87% | 26.04% |
| Thresholded Residual PageRank | 7.43% | 15.46% |

Freeze parameters and all input hashes with:

```bash
python3 scripts/freeze_current_fpga_spine_mechanism_components_v15.py
```

The frozen model, development predictions, workload hashes, hardware-log
hashes, simulator-result hashes, and contract hash are in
`docs/evaluation_refresh_20260810/calibration_v15_frozen/`.

After LJ/LJ08 finish, apply the frozen model without refitting:

```bash
python3 scripts/analyze_current_fpga_spine_mechanism_components_v15.py
```

No Fig. 8--10 timing claim is admitted unless correctness, structural work,
request/byte/FIFO ledgers, total timing, component timing, and rank gates pass.
