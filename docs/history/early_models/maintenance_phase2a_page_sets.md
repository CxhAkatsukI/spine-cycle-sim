# Phase 2A Maintenance Page-Set Model

This note records the Phase 2A structural fix for the B-stage maintenance
model. The goal is to reduce the largest known simulator/HW counter mismatch
without changing the broader timing calibration model.

## Baseline

Simulator repo:

```text
/home/chuxiao/spine-cycle-sim
base commit 0502014 Record first HW maintenance calibration
```

Existing HW evidence came from:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels
commit 05584da feat: stream sparse carry cursors
```

HW xclbin:

```text
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin
```

The key HW run was:

```bash
cd /home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration
source /opt/xilinx/xrt/setup.sh
unset XCL_EMULATION_MODE
export SPINE_PARTITIONED_SPLIT=1
X=/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin
./host_partitioned_csr_e2e_smoke "$X" --measure-carry 1 1024 64 --timeout 120
```

Observed HW counters:

```text
target_level=1
cold_page_ids_written=16
cold_pages_visited=16
cold_bits_inspected=4096
cold_rows_entered=16
cold_payload_reads=1024
cold_refill_stalls=4176
cold_merge_inputs=2048
cold_outputs=2048
```

## Problem

The Phase 1 simulator stored only page counts per family/level:

```text
level_page_counts[family][level]
```

During L1 carry it computed output pages as:

```text
old lower-level page count + new batch page count
```

That is wrong when old and new data touch the same source page. The HLS
page-list writer emits unique output page IDs, so overlapping old/new pages
must be coalesced. In the HW 1024-edge L1 carry case, each of the 16 cold
families has old data and new data in the same source page. HW writes 16 page
IDs, while the previous simulator estimated 32.

## Change

`Level0Buffer` now tracks page identity as well as page counts:

```text
level_page_sets[family][level]
```

For each maintenance group and target level, the simulator now computes:

```text
output_page_set =
    current_batch_page_set union all lower-level page sets consumed by carry

page_ids_written = len(output_page_set)
```

The old `level_page_counts` field is kept as a derived count because existing
result summaries and occupancy code already use count-shaped fields.

Important distinction:

```text
pages_visited
```

still counts old lower-level input page-list entries. It is not converted to a
union, because sparse carry cursors visit old input page lists level by level.
Only output page IDs are coalesced.

## Added Tests

New unit tests in:

```text
/home/chuxiao/spine-cycle-sim/tests/test_maintenance_timing.py
```

Cases:

| test | purpose |
| --- | --- |
| `test_l1_cascade_coalesces_output_pages_across_old_and_new_batch` | old and new batches touch the same source page; output page IDs must not double count |
| `test_l1_cascade_keeps_disjoint_output_pages` | old and new batches touch different source pages; output page IDs still add up |
| `test_hw_l1_measure_carry_1024_structural_page_counters` | simulator shape matching the recorded HW `--measure-carry 1 1024 64` structural counters |

The HW-shaped simulator test expects:

```text
target_level=1
pages_visited=16
bits_inspected=4096
rows_entered=16
payload_reads=1024
merge_inputs=2048
outputs=2048
page_ids_written=16
```

## Validation Commands

Run all unit tests:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 -m unittest discover -s tests -v
```

Observed result:

```text
Ran 14 tests in 7.212s
OK
```

Run maintenance microbenchmarks:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_maintenance_microbench.py \
  --out-dir results/maintenance_phase2a_microbench_check
```

Observed result:

```text
cold_l0_store_one_family: PASS cycles=494 maint_cycles=69 scan_passes=6 max_target=0
balanced_l1_cascade: PASS cycles=1917 maint_cycles=1484 scan_passes=14 max_target=1
concentrated_l1_overflow: FAIL cycles=24 maint_cycles=133 scan_passes=6 max_target=0
duplicate_l0_coalesce: PASS cycles=521 maint_cycles=64 scan_passes=3 max_target=0
hot_zero_input_group_scans: PASS cycles=3225 maint_cycles=2432 scan_passes=53 max_target=2
```

## Acceptance

Phase 2A is accepted if:

- Existing unit tests still pass.
- The two synthetic overlap/disjoint page tests pass.
- The HW-shaped L1 1024-edge structural test reports
  `page_ids_written=16`, not 32.
- Existing HW evidence remains the source of truth for the recorded hardware
  counter values; no new HW run is required for this phase.

## Remaining Limits

This phase does not fix absolute timing calibration. The hardware maintenance
time is still roughly 70x to 120x higher than the current simulator estimate in
the recorded HW runs.

This phase also does not model:

- AXI outstanding requests, burst packing, response FIFO depth, or refill
  stalls.
- AXIS stream backpressure between `rdmaint` and `compute`.
- Full CSR payload-level merge behavior.
- Duplicate coalescing across old levels and the new batch beyond page-list
  identity.
- Host sort time, PCIe transfer time, or XRT runtime overhead.

The safe claim after Phase 2A is:

```text
The simulator now matches the recorded HW L1 carry structural page counters for
the 1024-edge measure-carry case, including output page-list coalescing. It is
still not calibrated for absolute HW cycles.
```
