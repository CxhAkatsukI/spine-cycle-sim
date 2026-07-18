# Phase 1 B-Stage Maintenance Timing Model

This document records the current simulator update for matching the
`reduce-levels-for-routing` Spine HLS maintenance structure.

## Source Baseline

Hardware source inspected:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels
origin/reduce-levels-for-routing
commit 05584da feat: stream sparse carry cursors
```

Relevant HLS facts:

- `partitioned_run_maintenance` scans `sorted_edges` once to count hot/cold
  input edges.
- Cold families are processed first. Hot families are processed only when
  metadata hot mode is enabled.
- Target level is selected by the first empty binary level in the family range,
  not by waiting until a level is full.
- Target 0 uses the L0 store path. Target greater than 0 uses the sparse carry
  path.
- L0 store pre-counts every family in the group by scanning `sorted_edges`.
- Carry uses per-family `partitioned_new_batch_next_for_family`, so each
  family in the group can scan/filter the new batch.
- Sparse carry cursors visit page lists and page bitmaps. HLS page CSR uses
  `PAGE_CSR_VERTICES_PER_PAGE = 256`.

## Simulator Changes

The previous model treated B-stage routing as:

```text
EdgeInput -> PartitionRouter -> family FIFO -> immediate logical level update
```

The updated model keeps that ingestion path for workload bookkeeping, but adds
an HLS-style maintenance estimate to every `StorageEvent`.

Each event now records:

```text
group, path, target_level, batch_edges, input_edges, output_edges
scan_passes, scan_cycles
diagnostic_scan_passes, pre_count_scan_passes, write_scan_passes
new_batch_filter_passes
pages_visited, bits_inspected, rows_entered, payload_reads
merge_inputs, outputs, page_ids_written
estimated_cycles
```

The `Level1CarryMerge` component now waits for `estimated_cycles` before it
emits memory requests. This replaces the old optimistic
`ceil(edge_count / carry_merge_edges_per_cycle)` delay.

## Estimation Rules

For an L0 store event:

```text
diagnostic_scan_passes = 1 for the first processed group in a maintenance call
pre_count_scan_passes = family_count
write_scan_passes = number of nonempty output families
scan_cycles = scan_passes * batch_edges
write_output_cycles = output_edges + output_rows + output_pages
metadata_cycles = family_count
estimated_cycles = scan_cycles + write_output_cycles + metadata_cycles
```

For a carry event:

```text
diagnostic_scan_passes = 1 for the first processed group in a maintenance call
new_batch_filter_passes = family_count
scan_cycles = scan_passes * batch_edges
cursor_level_inits = family_count * target_level
pages_visited = old lower-level page count
bits_inspected = pages_visited * 256
payload_reads = old lower-level edge count
cursor_read_cycles = pages_visited * 7 + rows_entered * 2 + payload_reads
merge_inputs = old lower-level edges + new unique batch edges
write_output_cycles = output_edges + output_rows + output_pages
metadata_cycles = cursor_level_inits * 8 + family_count * 21
estimated_cycles =
    scan_cycles + cursor_read_cycles + bits_inspected
    + merge_inputs + write_output_cycles + metadata_cycles
```

These rules are intentionally conservative and structural. They are not yet a
cycle-exact AXI model.

## Microbenchmarks

Run:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_maintenance_microbench.py \
  --out-dir results/maintenance_phase1_microbench
```

Cases:

| case | purpose |
| --- | --- |
| `cold_l0_store_one_family` | L0 store scan passes: diagnostic + all-family pre-count + one write scan |
| `balanced_l1_cascade` | First-empty target selection and L1 sparse carry cursor work |
| `concentrated_l1_overflow` | Capacity failure at target L1 with `maintenance_path=cascade` |
| `duplicate_l0_coalesce` | Raw input edges versus coalesced L0 output edges |
| `hot_zero_input_group_scans` | Hot metadata enabled; zero-input groups still scan/carry old data |

Run tests:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 -m unittest discover -s tests -v
```

Acceptance criteria for Phase 1:

- The unit tests pass.
- Every successful maintenance event exposes path, target level, scan passes,
  cursor counters, and estimated cycles.
- Small balanced batches show `store_l0` followed by `cascade`.
- Concentrated low-level updates fail with `level_family_capacity` at target
  L1 when the target family capacity is exceeded.
- Hot-enabled workloads can show cold/hot group scans even when one group has
  zero new input.

## Current Limits

Do not claim these metrics as validated yet:

- exact hw/hw_emu cycle match
- AXI outstanding behavior
- AXIS stream depth/backpressure behavior between `rdmaint` and `compute`
- exact HBM burst and response FIFO timing
- exact duplicate coalescing across old levels and the new batch
- failed overflow events are detected before scheduling the failed event's full
  scan/carry timing; use the failure fields for capacity diagnosis, not the
  failed run's absolute cycles
- Vitis runtime, host sort time, PCIe transfer time
- FPGA-to-ASIC absolute performance extrapolation

The safe claim is narrower:

```text
The simulator now captures the dominant structural B-stage maintenance costs:
sorted_edges multi-pass scans, binary first-empty level selection, L0 store
versus carry path choice, sparse cursor/page work, and hot/cold group behavior.
It is suitable for trend checks and for designing hw/hw_emu calibration
microbenchmarks, not for final absolute-cycle claims.
```
