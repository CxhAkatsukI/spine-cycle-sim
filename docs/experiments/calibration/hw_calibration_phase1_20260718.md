# HW Calibration Phase 1 - 2026-07-18

This note records the first direct hardware calibration attempt for the
Phase 1 B-stage maintenance timing model.

## Artifacts

Simulator repo:

```text
/home/chuxiao/spine-cycle-sim
commit ad996f3 Model HLS-style maintenance timing
```

HLS source used for the host:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels
commit 05584da feat: stream sparse carry cursors
```

Host executable:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
sha256 4febd0568e9e910cde1188d058f33e342eb537aef312796d911f5b72cc2c47fb
```

HW xclbin:

```text
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin
sha256 4d28a2d2420d4524c7c7fcf48239c027b29fa63d49351ecfcdd8cf0aa37db91d
```

The xclbin info reports:

```text
Kernels: spine_partconv_compute_kernel, spine_partconv_rdmaint_kernel
Requested kernel frequency: 134 MHz
Achieved kernel frequency: 134 MHz
```

Host build command:

```bash
cd /home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration
source /opt/xilinx/xrt/setup.sh
make host_partitioned_csr_e2e_smoke TARGET=hw KERNEL_FREQ=150 -j4
```

Run environment:

```bash
source /opt/xilinx/xrt/setup.sh
unset XCL_EMULATION_MODE
export SPINE_PARTITIONED_SPLIT=1
```

## HW Commands

L0 store:

```bash
X=/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin
./host_partitioned_csr_e2e_smoke "$X" --star 256 --timeout 120
./host_partitioned_csr_e2e_smoke "$X" --star 1024 --timeout 120
./host_partitioned_csr_e2e_smoke "$X" --star 4096 --timeout 120
```

L1 carry:

```bash
X=/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin
./host_partitioned_csr_e2e_smoke "$X" --measure-carry 1 1 1 --timeout 120
./host_partitioned_csr_e2e_smoke "$X" --measure-carry 1 256 64 --timeout 120
./host_partitioned_csr_e2e_smoke "$X" --measure-carry 1 1024 64 --timeout 120
./host_partitioned_csr_e2e_smoke "$X" --measure-carry 1 4096 64 --timeout 120
```

## HW Results

All listed runs reported `PASS`.

| path | edges | hw maint ms | hw cycles at 134 MHz | simulator cycles | hw/sim |
| --- | ---: | ---: | ---: | ---: | ---: |
| L0 store | 256 | 7.20413 | 965,353 | 8,752 | 110.3 |
| L0 store | 1024 | 27.6916 | 3,710,674 | 34,864 | 106.4 |
| L0 store | 4096 | 109.695 | 14,699,130 | 139,312 | 105.5 |
| L1 carry | 1 | 0.340311 | 45,602 | n/a | n/a |
| L1 carry | 256 | 5.72465 | 767,103 | 10,400 | 73.8 |
| L1 carry | 1024 | 21.1603 | 2,835,480 | 27,296 | 103.9 |
| L1 carry | 4096 | 83.1848 | 11,146,763 | 94,880 | 117.5 |

L0 store examples:

```text
PARTITIONED_CSR_E2E_BATCH case=star batch=1 input_edges=1024 target_level=0 consumed_mask=0 persisted=1024 overflow=0 l0_partitions_written=16 l0_pages_epoch_stamped=16 maint_ms=27.6916
```

L1 carry examples:

```text
PARTITIONED_CSR_E2E_MEASURE_CARRY_COUNTERS target_level=1 cold_page_ids_written=16 cold_pages_visited=16 cold_bits_inspected=4096 cold_rows_entered=16 cold_payload_reads=1024 cold_refill_stalls=4176 cold_merge_inputs=2048 cold_outputs=2048
PARTITIONED_CSR_E2E_MEASURE_CARRY PASS target_level=1 batch_edges=1024 source_count=64 preloaded_edges=1024 persisted=2048 maint_ms=21.1603 timeout_s=120 errors=0
```

## Simulator Comparison

The simulator matches the key structural counters for the L1 1024-edge case:

```text
target_level=1
pages_visited=16
bits_inspected=4096
rows_entered=16
payload_reads=1024
merge_inputs=2048
outputs=2048
```

One counter does not match:

```text
HW page_ids_written = 16
sim page_ids_written = 32
```

Cause: the simulator currently stores only per-level page counts and sums old
level pages plus new-batch pages. In this workload, old and new sources are in
the same source page, so the real HLS page-list writer coalesces them to 16
output page IDs. The simulator overcounts output pages because it does not keep
per-family page sets across old levels and the new batch.

## Current Conclusion

The Phase 1 simulator is structurally aligned enough to predict:

- `store_l0` versus `cascade`
- `target_level`
- cold carry counters such as pages visited, bits inspected, payload reads,
  merge inputs, and outputs
- linear trend versus edge count

It is not yet calibrated for absolute B-stage cycles. The observed hardware
maintenance time is roughly 70x to 120x higher than the current simulator
estimate on these direct HW cases.

The next simulator changes should be:

1. Track page sets per family/level so `page_ids_written` coalesces old and new
   pages like HLS.
2. Add an explicit calibration layer for external-memory/pipeline cost instead
   of assuming each HLS scan iteration costs one simulator cycle.
3. Preserve structural counters separately from calibrated cycle estimates so
   we can keep counter validation and timing calibration independent.
