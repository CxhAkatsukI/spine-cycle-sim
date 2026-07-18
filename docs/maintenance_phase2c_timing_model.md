# Phase 2C Calibrated Maintenance Timing Model

This note records the first calibrated B-stage maintenance timing model derived
from the Phase 2B HW sweep.

## Source Evidence

HW calibration directory:

```text
/home/chuxiao/spine-cycle-sim/results/maintenance_phase2b_hw_20260718_225611
```

Findings note:

```text
/home/chuxiao/spine-cycle-sim/docs/maintenance_phase2b_hw_findings_20260718.md
```

Phase 2B result:

```text
19 cases * 3 repeats = 57 HW runs
all PASS
```

Main measured bottleneck:

```text
repeated sorted_edges scan/filter work over the new update batch
```

## Model Goal

The previous model used:

```text
scan_cycles = scan_passes * batch_edges
```

This treated every HLS scan iteration as one simulator cycle. The Phase 2B HW
sweep showed that scan-heavy paths are roughly 100x slower than this structural
count.

The Phase 2C goal is to add a calibrated empirical timing layer while keeping
the original structural counters visible.

## Config Knobs

The current defaults are in `SpineConfig`:

```text
maintenance_calibrated_timing = True
maintenance_schedule_calibrated_cycles = False

maintenance_l0_scan_iteration_cycles = 105
maintenance_l0_output_edge_cycles = 110

maintenance_carry_scan_iteration_cycles = 145
maintenance_carry_payload_output_edge_cycles = 80
maintenance_carry_row_cursor_cycles = 130

maintenance_refill_stalls_per_page = 261
maintenance_refill_stall_cycles = 1
```

These coefficients are empirical Phase 2B calibration values. They are not an
AXI/HBM transaction-level model.

## L0 Store Formula

Structural counters are still:

```text
scan_passes = diagnostic + family pre-count scans + nonempty write scans
scan_cycles = scan_passes * batch_edges
write_output_cycles = output_edges + output_rows + output_pages
```

Calibrated estimate:

```text
calibrated_scan_cycles =
    scan_cycles * maintenance_l0_scan_iteration_cycles

calibrated_write_output_cycles =
    output_edges * maintenance_l0_output_edge_cycles
  + output_rows
  + output_pages

estimated_cycles =
    calibrated_scan_cycles
  + calibrated_write_output_cycles
  + metadata_cycles
```

This matches the L0 HW sweep because large L0 store cases stabilize around
3575 HW cycles per input edge:

```text
33 scan passes * 105 cycles + 110 output cycles ~= 3575 cycles/edge
```

## Carry Formula

Structural counters are still:

```text
scan_passes = diagnostic + family new-batch filter scans
scan_cycles = scan_passes * batch_edges
pages_visited = old lower-level page-list entries
rows_entered = old lower-level rows
payload_reads = old lower-level edges
outputs = old edges + new unique batch edges
```

The simulator now estimates refill stalls using the HW-observed relation:

```text
refill_stalls = pages_visited * maintenance_refill_stalls_per_page
```

Calibrated estimate:

```text
calibrated_scan_cycles =
    scan_cycles * maintenance_carry_scan_iteration_cycles

calibrated_merge_cycles =
    (payload_reads + outputs) * maintenance_carry_payload_output_edge_cycles

calibrated_row_cursor_cycles =
    rows_entered * maintenance_carry_row_cursor_cycles

calibrated_refill_stall_cycles =
    refill_stalls * maintenance_refill_stall_cycles

estimated_cycles =
    calibrated_scan_cycles
  + calibrated_merge_cycles
  + calibrated_row_cursor_cycles
  + calibrated_refill_stall_cycles
  + output_pages
  + metadata_cycles
```

The carry scan cost is higher than L0 scan cost because the carry path performs
per-family new-batch filtering and merge/write work around the scan path.

## Scheduling Strategy

The Python simulator is still a per-cycle event loop. Scheduling a full-batch
L0 store with calibrated cycles would require hundreds of millions of empty
ticks.

To keep simulation usable:

```text
estimated_cycles = calibrated performance estimate
structural_estimated_cycles = old structural timing estimate
scheduled_cycles = structural_estimated_cycles by default
```

`Level1CarryMerge` waits for `scheduled_cycles`, not `estimated_cycles`, unless
`maintenance_schedule_calibrated_cycles=True`.

The final result adjusts performance cycles after the run:

```text
calibrated_extra_cycles =
    maintenance_estimated_cycles - maintenance_scheduled_cycles

cycles =
    execution_cycles + calibrated_extra_cycles
```

The result keeps both:

```text
execution_cycles
cycles
calibrated_cycles
maintenance_structural_estimated_cycles
maintenance_calibrated_estimated_cycles
maintenance_scheduled_cycles
```

Use `cycles` or `calibrated_cycles` for performance estimates. Use
`execution_cycles` only to understand Python simulation runtime.

## Validation

Validation command:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/analyze_hw_maintenance_calibration.py \
  --input-dir results/maintenance_phase2b_hw_20260718_225611 \
  --out-dir results/maintenance_phase2c_calibrated_check \
  --freq-mhz 134
```

Observed result:

```text
19/19 cases within 10% absolute error
median absolute error: 0.46%
max absolute error: 8.27%
```

Worst case:

```text
carry_l1_batch_e256_s64
HW cycles: 762,274
predicted cycles: 699,216
error: -8.27%
```

Representative case:

```text
carry_l1_batch_e1024_s64
HW cycles: 2,840,371
structural estimate: 27,280
calibrated estimate: 2,776,656
error: -2.24%
```

Error by sweep:

| sweep | median abs error | max abs error |
| --- | ---: | ---: |
| `l0_store` | 0.23% | 5.51% |
| `l1_batch_edges` | 0.47% | 8.27% |
| `source_count` | 0.78% | 1.31% |
| `target_level` | 0.34% | 0.49% |

## Tests

Run:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 -m unittest discover -s tests -v
```

The HW-shaped L1 1024-edge test now checks:

```text
structural_estimated_cycles = 27,280
scheduled_cycles = 27,280
estimated_cycles = 2,776,656
refill_stalls = 4,176
```

## Current Limits

This is still an empirical timing layer. Do not claim:

```text
cycle-accurate AXI/HBM behavior
AXIS stream backpressure accuracy
D-stage SSSP/end-to-end calibration
final paper-quality absolute performance accuracy
```

Safe claim:

```text
For the Phase 2B B-stage maintenance microbenchmarks, the calibrated simulator
now predicts HW maintenance cycles within 10% on all measured points, while
preserving structural counters separately from calibrated timing.
```

## Next Step

The next architectural simulator work should be:

1. Add transaction-level HBM/AXI modeling for residual memory effects.
2. Model rdmaint-to-compute AXIS stream backpressure.
3. Calibrate D-stage SSSP independently.
4. Use real graph workloads as holdout validation after B and D are separated.
