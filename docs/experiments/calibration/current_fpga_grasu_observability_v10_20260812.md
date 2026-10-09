# Current-FPGA G+R observability freeze (v10)

## Purpose

The v10 SST plugin closes an evidence gap in the frozen current-FPGA
calibration campaign. The v9 execution model already represented normalized,
conversion-free, sharded-K4 GraSU+ReGraph, but the connected-components result
did not serialize enough internal counters to audit the memory and bounded-FIFO
contracts used by Figures 9 and 10.

This revision changes result observability only. It does not change request
generation, scheduling, cycle advancement, HBM timing, FIFO capacity, algorithm
semantics, or the simulated total cycle count.

## Immutable identities

- Plugin: `cpp/sst/build/sst-current-fpga-v10/libspine_cycle.so`
- SHA-256: `42bafbee3b116d61d7b1bcbb51da6c67e0993fd771b7b59f3354360ce1e5302a`
- Calibration contract: `configs/contracts/evaluation_refresh_fpga_calibration_v6.json`
- Case contract: `configs/contracts/evaluation_refresh_fpga_cases_v5.json`
- Clean evidence root: `/data/tmp/chuxiao/evaluation_refresh_current_fpga_v10_20260812`
- Calibration datasets: AU and SU
- Holdout datasets: WK and R19

No v9 result may be copied into the v10 evidence root or used to fit a v10
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

## Smoke validation

The final plugin was built and exercised independently for all G+R algorithms:

| Algorithm | Cycles | Key result | Ledger |
|---|---:|---|---|
| Weighted SSSP | 99,885 | update 121; compute 99,763 | PASS |
| Connected components | 167,856 | 4 iterations | PASS |
| Thresholded residual PageRank | 1,487,890 | 10 iterations; 48 active edges | PASS |

Smoke roots:

- `/data/tmp/chuxiao/current_fpga_v10_final_weighted_smoke_20260812`
- `/data/tmp/chuxiao/current_fpga_v10_final_cc_smoke_20260812`
- `/data/tmp/chuxiao/current_fpga_v10_final_residual_smoke_20260812`

Each row passed correctness, structured phase-traffic closure, backend request
closure, compute AXI issue/completion equality, and all observable FIFO bounds.
These smokes establish instrument validity only; they are not calibration or
holdout performance samples.

## Reproduction

```bash
make -C cpp/sst BUILD_DIR=build/sst-current-fpga-v10 -j8
sha256sum cpp/sst/build/sst-current-fpga-v10/libspine_cycle.so

python3 -m unittest \
  tests.test_current_fpga_component_evidence \
  tests.test_memory_traffic \
  tests.test_current_fpga_calibration_freeze
```

After all AU/SU rows pass, freeze calibration before starting WK/R19:

```bash
python3 scripts/freeze_current_fpga_calibration_v4.py
```
