# Phase 2B HW Maintenance Findings - 2026-07-18

This note records the first full Phase 2B black-box HW maintenance calibration
run.

## Artifacts

Simulator repo:

```text
/home/chuxiao/spine-cycle-sim
commit ce1d7be Add HW maintenance calibration tooling
```

HW xclbin:

```text
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin
sha256 4d28a2d2420d4524c7c7fcf48239c027b29fa63d49351ecfcdd8cf0aa37db91d
```

Host executable:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
sha256 4febd0568e9e910cde1188d058f33e342eb537aef312796d911f5b72cc2c47fb
```

Output directory:

```text
/home/chuxiao/spine-cycle-sim/results/maintenance_phase2b_hw_20260718_225611
```

Important files:

```text
runs.csv
summary.csv
analysis/summary.csv
analysis/fit.json
analysis_with_sim/summary.csv
analysis_with_sim/fit.json
raw/<case>/run_N.stdout
raw/<case>/run_N.stderr
raw/<case>/run_N.command.sh
```

The `analysis` directory is HW-only. The `analysis_with_sim` directory appends
lightweight simulator structural estimates.

## Commands

Dry-run:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_hw_maintenance_calibration.py \
  --xclbin /data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin \
  --out-dir results/maintenance_phase2b_hw_20260718_225611 \
  --dry-run
```

HW sweep:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_hw_maintenance_calibration.py \
  --xclbin /data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin \
  --out-dir results/maintenance_phase2b_hw_20260718_225611 \
  --repeats 3 \
  --timeout 300 \
  --freq-mhz 134 \
  --allow-failures
```

Analysis:

```bash
python3 scripts/analyze_hw_maintenance_calibration.py \
  --input-dir results/maintenance_phase2b_hw_20260718_225611 \
  --freq-mhz 134 \
  --skip-simulator

python3 scripts/analyze_hw_maintenance_calibration.py \
  --input-dir results/maintenance_phase2b_hw_20260718_225611 \
  --out-dir results/maintenance_phase2b_hw_20260718_225611/analysis_with_sim \
  --freq-mhz 134
```

## Run Status

The dry-run generated:

```text
cases=19 repeats=3 total_runs=57
```

All 57 HW runs completed with `PASS`.

Most measured points had low repeat jitter. The largest jitter in this run was
below 1%, so the median values are stable enough for first-pass bottleneck
analysis.

## Main Observations

### 1. L0 Store Is Almost Perfectly Linear In Batch Edges

| case | median ms | HW cycles @134 MHz | cycles / edge |
| --- | ---: | ---: | ---: |
| `l0_store_e256` | 7.229 | 968,647 | 3,784 |
| `l0_store_e1024` | 27.684 | 3,709,656 | 3,623 |
| `l0_store_e4096` | 109.693 | 14,698,862 | 3,589 |
| `l0_store_e16384` | 437.480 | 58,622,320 | 3,578 |
| `l0_store_e65536` | 1748.770 | 234,335,180 | 3,576 |
| `l0_store_e131072` | 3497.180 | 468,622,120 | 3,575 |

Interpretation:

```text
L0 maintenance is dominated by per-edge sorted_edges scan/store work.
```

For large batches, the cost is about 3.58k HW cycles per input edge. Because
the L0 path scans the batch many times, this corresponds to roughly 100-cycle
scale cost per HLS scan iteration, not one simulator cycle per scan iteration.

### 2. L1 Batch-Edges Sweep Also Scales With New Batch Size

| case | median ms | HW cycles | cycles / new edge | cycles / persisted edge |
| --- | ---: | ---: | ---: | ---: |
| `carry_l1_batch_e256_s64` | 5.689 | 762,274 | 2,978 | 1,489 |
| `carry_l1_batch_e1024_s64` | 21.197 | 2,840,371 | 2,774 | 1,387 |
| `carry_l1_batch_e4096_s64` | 83.129 | 11,139,299 | 2,720 | 1,360 |
| `carry_l1_batch_e16384_s64` | 330.952 | 44,347,568 | 2,707 | 1,353 |
| `carry_l1_batch_e65536_s64` | 1322.010 | 177,149,340 | 2,703 | 1,352 |

Counters for these points keep pages/rows/refill almost constant:

```text
cold_pages_visited=16
cold_rows_entered=16
cold_refill_stalls=4176
```

while payload/merge/output scale with edge count.

Interpretation:

```text
For target-1 carry, batch size dominates. The new sorted_edges filtering scans
are still a major cost.
```

### 3. Old Payload Merge Is Much Cheaper Than Large New-Batch Scans

The source-count sweep keeps the new batch tiny (`batch_edges=128`) but carries
about 65k old payload edges:

| case | median ms | HW cycles | payload reads | outputs | rows entered |
| --- | ---: | ---: | ---: | ---: | ---: |
| `carry_source_t9_e128_s1` | 81.643 | 10,940,162 | 65,408 | 65,536 | 144 |
| `carry_source_t9_e128_s16` | 82.507 | 11,055,992 | 65,408 | 65,536 | 1,520 |
| `carry_source_t9_e128_s64` | 84.394 | 11,308,756 | 65,408 | 65,536 | 4,080 |
| `carry_source_t9_e128_s256` | 88.068 | 11,801,058 | 65,408 | 65,536 | 8,176 |
| `carry_source_t9_e128_s512` | 89.934 | 12,051,196 | 65,408 | 65,536 | 8,176 |

Interpretation:

```text
Carrying about 65k old edges costs around 11-12M cycles, far below the
177M-cycle target-1 case with a 65k new batch.
```

This is strong evidence that the current bottleneck is not simply "HBM old edge
payload merge". The repeated new-batch scan/filter path is much more expensive
when the update batch is large.

### 4. Row Locality Has A Real But Secondary Cost

In the source-count sweep, payload/output volume is fixed, but rows increase
from 144 to 8176. Runtime increases from about 81.6 ms to 89.9 ms.

Interpretation:

```text
More rows/pages hurt, but this effect is secondary compared with scan-heavy
large update batches.
```

The rough incremental row cost from this sweep is on the order of 100-cycle
scale per row. It is measurable, but it is not the dominant first-order term.

### 5. Higher Target Levels Add Cost, But Still Less Than Huge New Batches

| case | median ms | HW cycles | payload reads | outputs | pages visited |
| --- | ---: | ---: | ---: | ---: | ---: |
| `carry_target_l2_e4096_s64` | 93.034 | 12,466,543 | 12,288 | 16,384 | 32 |
| `carry_target_l3_e4096_s64` | 112.615 | 15,090,410 | 28,672 | 32,768 | 48 |
| `carry_target_l4_e4096_s64` | 151.549 | 20,307,566 | 61,440 | 65,536 | 64 |

Incrementally, this suggests old payload/output work is roughly 160 cycles per
additional old/output edge in this controlled region. That is meaningful, but
still far below the scan-heavy cost seen when the new update batch itself is
large.

## Fit Results

HW-only top univariate feature:

```text
batch_edges: r2=0.9860
```

With lightweight simulator structural estimates:

```text
sim_maintenance_estimated_cycles: r2=0.9935
batch_edges: r2=0.9860
```

Interpretation:

```text
The simulator's structural model captures the trend shape because it includes
scan passes and carry structure. It still underestimates absolute HW cycles by
large, path-dependent factors.
```

Observed HW/sim ratio by sweep:

| sweep | median HW/sim ratio | interpretation |
| --- | ---: | --- |
| `l0_store` | 105x | stable scan-heavy L0 path |
| `l1_batch_edges` | 117x | scan-heavy carry with large new batch |
| `source_count` | 46x | old-carry-heavy path with tiny new batch |
| `target_level` | 85x | mixed new scan plus old carry |

This proves a single global multiplier is not the right next model.

## Bottleneck Conclusion

The main B-stage bottleneck exposed by this run is:

```text
repeated sorted_edges scan/filter work over the new update batch
```

The second-order costs are:

```text
old payload/output merge
row locality / cursor traversal
target-level carry depth
```

`refill_stalls` is visible and should remain in the model, but this run does
not show it as the dominant first-order explanation. In these controlled cases,
scan-heavy large batches dominate much more strongly.

## Implications For Simulator Calibration

The next timing model should not use:

```text
scan_cycles = scan_passes * batch_edges
```

with one simulator cycle per scan iteration.

Instead, the calibrated model should split at least these terms:

```text
scan_iteration_cycles ~= 100-160 HW cycles per scan iteration
old_payload_output_cycles ~= 160 HW cycles per old/output edge in controlled carry
row_cursor_cycles ~= 100-cycle scale per row
fixed/path overhead
```

The exact coefficients should be fitted from the saved CSVs, but the structure
should be path-aware:

```text
L0 store != L1 large-new-batch carry != high-level old-carry-heavy merge
```

## Claims Allowed

Allowed:

```text
The first full HW calibration sweep shows B-stage maintenance time is dominated
by repeated scan/filter work over sorted_edges for large update batches.
```

Allowed:

```text
Old-level payload merge and row/page locality are measurable but secondary in
the tested cases.
```

Not allowed:

```text
The simulator is now absolute-cycle accurate.
```

Not allowed:

```text
D-stage SSSP or end-to-end Spine performance is calibrated by this run.
```

## Next Step

Implement a Phase 2C timing model update:

1. Replace one-cycle scan iterations with calibrated scan costs.
2. Split L0 store, large-new-batch carry, and old-carry-heavy merge costs.
3. Keep structural counters separate from calibrated cycle estimates.
4. Re-run the same Phase 2B analyzer and check whether most stable HW points
   fall within the 30%-40% first-pass error target.
