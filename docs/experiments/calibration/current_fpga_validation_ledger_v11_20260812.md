# Current-FPGA validation-ledger freeze (v11)

## Purpose

The v11 SST plugin retains the complete G+R observability introduced by v10 and
fixes a fail-closed validation error exposed by a nonzero-propagation residual
PageRank case. The top-level per-round request identity omitted the owner-FIFO
HBM protocol even though those requests were already generated, timed, and
reported by the execution model.

This revision changes only the validation identity. It does not change request
generation, scheduling, cycle advancement, HBM timing, FIFO capacity, algorithm
semantics, or simulated cycles. The corrected identity is:

`round requests = legacy PageRank requests + owner-FIFO HBM requests`.

## Immutable identities

- Plugin: `cpp/sst/build/sst-current-fpga-v11/libspine_cycle.so`
- SHA-256: `942905262934ec0fd166d2aa442e98b229da8647e611fc1d723c7650cd516705`
- Calibration contract: `configs/contracts/evaluation_refresh_fpga_calibration_v7.json`
- Case contract: `configs/contracts/evaluation_refresh_fpga_cases_v6.json`
- Clean evidence root: `/data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_20260812`
- Calibration datasets: AU and SU
- Holdout datasets: WK and R19

No v10 result may be copied into the v11 evidence root or used to fit a v11
scale. Holdout rows may validate frozen scales but may never fit them.

## Added result evidence

All three G+R algorithms now expose the counters required by the common ledger
validator:

- update, compute, and total backend request counts;
- structured update/compute read, write, byte, and locality ledgers;
- compute AXI beats issued and completed;
- frozen FIFO depths and observed maximum occupancies;
- adapter AXIS depth and push stalls;
- AXI issue/backend stalls and HBM submit/response-queue stalls.

Only FIFO boundaries represented as explicit queues in the execution model are
claimed as bounded and checked. The adapter has a serialized finite depth and
stall count; it does not claim an independent occupancy counter where the model
does not maintain one.

## Validation

The retained v10 G+R instrumentation was previously exercised independently for
all three algorithms:

| Algorithm | Cycles | Key result | Ledger |
|---|---:|---|---|
| Weighted SSSP | 99,885 | update 121; compute 99,763 | PASS |
| Connected components | 167,856 | 4 iterations | PASS |
| Thresholded residual PageRank | 1,487,890 | 10 iterations; 48 active edges | PASS |

Those v10 smoke roots remain observability-development evidence only:

- `/data/tmp/chuxiao/current_fpga_v10_final_weighted_smoke_20260812`
- `/data/tmp/chuxiao/current_fpga_v10_final_cc_smoke_20260812`
- `/data/tmp/chuxiao/current_fpga_v10_final_residual_smoke_20260812`

The v11 validation fix was exercised on a real-topology Flickr residual
PageRank update with 8,192 resident edges. It propagated for 12 rounds, passed
both correctness oracles, and closed the owner round, owner HBM request/byte,
active-edge, phase-traffic, and total-memory ledgers. This case would fail the
v10 top-level formula by exactly the owner request count in every round.

The v10 smokes and v11 Flickr row are not calibration or holdout performance
samples. All AU/SU calibration and WK/R19 holdout rows are rerun with v11.

## Reproduction

```bash
make -C cpp/sst BUILD_DIR=build/sst-current-fpga-v11 -j8
sha256sum cpp/sst/build/sst-current-fpga-v11/libspine_cycle.so

python3 -m unittest \
  tests.test_current_fpga_component_evidence \
  tests.test_memory_traffic \
  tests.test_current_fpga_calibration_freeze \
  tests.test_current_fpga_rq3_v11
```

After all AU/SU rows pass, freeze calibration before starting WK/R19:

```bash
python3 scripts/freeze_current_fpga_calibration_v4.py
```

## End-to-end evidence sequence

Run the six Spine and six G+R calibration cases on AU/SU. The runners reuse a
case only when its manifest has the same v11 plugin and profile hashes.

```bash
python3 scripts/run_current_fpga_spine_compacted_matrix.py \
  --simulation-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_20260812 \
  --lib-dir cpp/sst/build/sst-current-fpga-v11 \
  --dataset au --dataset su --jobs 3 --memory-reserve-gib 64

python3 scripts/run_current_fpga_grasu_frozen_matrix.py \
  --simulation-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_20260812 \
  --lib-dir cpp/sst/build/sst-current-fpga-v11 \
  --dataset au --dataset su --jobs 2 --memory-reserve-gib 64
```

Freeze and commit the fitted scales before creating any WK/R19 result. The
freeze script fails if a holdout `result.json` is already present.

```bash
python3 scripts/freeze_current_fpga_calibration_v4.py
git add docs/evaluation_refresh_20260810/calibration_v11_frozen
git commit -m "Freeze v11 calibration before holdout"
git push origin main
```

Only after that commit, run the independent holdout. The G+R runner schedules
WK normally and forces R19 to one job because R19 is the memory and wall-time
long tail.

```bash
python3 scripts/run_current_fpga_spine_compacted_matrix.py \
  --simulation-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_20260812 \
  --lib-dir cpp/sst/build/sst-current-fpga-v11 \
  --dataset wk --dataset r19 --jobs 2 --memory-reserve-gib 64

python3 scripts/run_current_fpga_grasu_frozen_matrix.py \
  --simulation-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_20260812 \
  --lib-dir cpp/sst/build/sst-current-fpga-v11 \
  --dataset wk --dataset r19 --jobs 2 --memory-reserve-gib 64
```

The setup-inclusive update-only matrix can run alongside holdout after the
freeze commit. It executes AU-512 once and publishes that result into both the
cross-dataset and batch-sensitivity views.

```bash
python3 scripts/run_current_fig8_update_only_matrix.py \
  --evidence-root \
    /data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_fig8_20260812 \
  --frozen-models-dir \
    docs/evaluation_refresh_20260810/calibration_v11_frozen \
  --jobs 3 --memory-reserve-gib 64
```

The finalizer is deliberately fail-closed. It applies only the frozen AU/SU
models to WK/R19, requires every total/component/ledger/structural gate to
pass, exports Fig. 8 and Fig. 9, rebuilds the current RQ3 package for Fig. 10,
renders the figures, and requires the alignment audit to report `READY`.

```bash
python3 scripts/finalize_current_fpga_evaluation_v11.py
```

Important output locations are:

- frozen scales: `docs/evaluation_refresh_20260810/calibration_v11_frozen/`;
- independent calibration report:
  `docs/evaluation_refresh_20260810/calibration_v11_analysis/`;
- Fig. 8 ledger-gated data:
  `docs/evaluation_refresh_20260810/fig8_current_v11/`;
- Fig. 9 ledger-gated data:
  `docs/evaluation_refresh_20260810/fig9_current_v11/`;
- RQ3 package:
  `/data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_rq3_20260812/package/`;
- final audit:
  `docs/evaluation_refresh_20260810/provenance/alignment_audit.json`;
- final evidence manifest:
  `docs/evaluation_refresh_20260810/provenance/current_fpga_v11_finalization.json`.

No failed correctness row, failed ledger row, partial run, projected value, or
holdout-fitted parameter is admitted by this sequence.
