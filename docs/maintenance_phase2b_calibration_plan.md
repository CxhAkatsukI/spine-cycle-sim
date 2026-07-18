# Phase 2B HW Maintenance Calibration Plan

This phase calibrates the B-stage maintenance timing model against the existing
Spine HW build as a black-box experiment. It does not modify HLS code and does
not require rebuilding the xclbin.

## Scope

In scope:

- Run maintenance-only HW microbenchmarks with the existing
  `host_partitioned_csr_e2e_smoke` executable.
- Repeat every HW point three times.
- Preserve raw stdout/stderr and command logs.
- Parse existing host stdout fields.
- Convert `maint_ms` to HW cycles at the xclbin frequency.
- Merge simulator structural counters for the same synthetic workload shape.
- Fit lightweight empirical models to identify dominant timing terms.

Out of scope:

- D-stage SSSP/end-to-end compute calibration.
- HLS loop instrumentation.
- AXI/HBM cycle-accurate modeling.
- XRT runtime, PCIe transfer, and host sort time modeling.
- Claims of final absolute-cycle accuracy.

## Existing HW Interface

The runner uses the current host executable:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
```

Expected xclbin for the current evidence path:

```text
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin
```

Runtime environment:

```bash
source /opt/xilinx/xrt/setup.sh
unset XCL_EMULATION_MODE
export SPINE_PARTITIONED_SPLIT=1
```

The host already prints the fields needed for this phase.

L0 store line:

```text
PARTITIONED_CSR_E2E_BATCH ... target_level=0 ... persisted=... overflow=0 l0_partitions_written=... l0_pages_epoch_stamped=... maint_ms=...
```

Carry lines:

```text
PARTITIONED_CSR_E2E_MEASURE_CARRY_COUNTERS target_level=... cold_page_ids_written=... cold_pages_visited=... cold_bits_inspected=... cold_rows_entered=... cold_payload_reads=... cold_refill_stalls=... cold_merge_inputs=... cold_outputs=...
PARTITIONED_CSR_E2E_MEASURE_CARRY PASS target_level=... batch_edges=... source_count=... preloaded_edges=... persisted=... maint_ms=...
```

## Experiment Matrix

The default matrix has 19 cases. With the default `--repeats 3`, this is 57 HW
runs.

### L0 Store Sweep

Purpose: isolate the baseline cost of `sorted_edges` scanning and L0 store.

```text
--star 256
--star 1024
--star 4096
--star 16384
--star 65536
--star 131072
```

### L1 Carry Batch-Edges Sweep

Purpose: vary edge volume while holding `target_level=1` and
`source_count=64`.

```text
--measure-carry 1 256 64
--measure-carry 1 1024 64
--measure-carry 1 4096 64
--measure-carry 1 16384 64
--measure-carry 1 65536 64
```

### Source-Count Sweep

Purpose: vary row/page locality while holding total old payload volume near
65k edges. This uses `target_level=9` and `batch_edges=128`; a target-1 source
sweep is not useful because only two batches participate and the command can
only exercise at most two source IDs. Target 9 is used instead of target 10 to
avoid making every run allocate the full largest fixed layout.

```text
--measure-carry 9 128 1
--measure-carry 9 128 16
--measure-carry 9 128 64
--measure-carry 9 128 256
--measure-carry 9 128 512
```

### Target-Level Sweep

Purpose: vary binary carry depth while holding `batch_edges=4096` and
`source_count=64`. The `target_level=1` baseline is already covered by the
batch/source sweeps, so the default target sweep adds levels 2-4.

```text
--measure-carry 2 4096 64
--measure-carry 3 4096 64
--measure-carry 4 4096 64
```

## Runner

Dry-run first:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_hw_maintenance_calibration.py \
  --xclbin /data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin \
  --out-dir results/maintenance_phase2b_hw_$(date +%Y%m%d_%H%M%S) \
  --dry-run
```

Run HW:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_hw_maintenance_calibration.py \
  --xclbin /data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin \
  --out-dir results/maintenance_phase2b_hw_$(date +%Y%m%d_%H%M%S) \
  --repeats 3 \
  --timeout 120 \
  --freq-mhz 134
```

Useful narrower runs:

```bash
python3 scripts/run_hw_maintenance_calibration.py \
  --xclbin "$X" \
  --out-dir results/maintenance_phase2b_l0_only \
  --only-sweep l0_store \
  --repeats 3 \
  --timeout 120

python3 scripts/run_hw_maintenance_calibration.py \
  --xclbin "$X" \
  --out-dir results/maintenance_phase2b_carry_only \
  --only-sweep l1_batch_edges \
  --only-sweep source_count \
  --only-sweep target_level \
  --repeats 3 \
  --timeout 120
```

## Runner Outputs

```text
matrix.json              experiment matrix
metadata.json            xclbin, host executable, frequency, repeat count
commands.sh              exact shell commands
runs.csv                 one row per run
runs.json                JSON version of runs.csv
summary.csv              one row per case, median/min/max summarized
summary.json             JSON version of summary.csv
raw/<case>/run_N.stdout  raw host stdout
raw/<case>/run_N.stderr  raw host stderr
raw/<case>/run_N.command.sh
```

Raw logs should usually not be committed unless they are small and needed as
review evidence. Summary CSV/JSON files are the preferred artifacts.

## Analyzer

Run after HW collection:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/analyze_hw_maintenance_calibration.py \
  --input-dir results/maintenance_phase2b_hw_<timestamp> \
  --freq-mhz 134
```

Analyzer outputs:

```text
analysis/summary.csv
analysis/summary.json
analysis/fit.json
```

By default, the analyzer also runs the simulator on the matching synthetic
shape and appends `sim_*` counters. If this is too slow during iteration:

```bash
python3 scripts/analyze_hw_maintenance_calibration.py \
  --input-dir results/maintenance_phase2b_hw_<timestamp> \
  --skip-simulator
```

## Key CSV Fields

Raw run fields:

```text
case, sweep, mode, repeat, status, returncode
target_level, batch_edges, source_count
maint_ms, hw_cycles
```

L0 fields:

```text
persisted
l0_partitions_written
l0_pages_epoch_stamped
```

Carry fields:

```text
cold_page_ids_written
cold_pages_visited
cold_bits_inspected
cold_rows_entered
cold_payload_reads
cold_refill_stalls
cold_merge_inputs
cold_outputs
```

Summary fields:

```text
median_maint_ms, min_maint_ms, max_maint_ms
median_hw_cycles, min_hw_cycles, max_hw_cycles
maint_ms_jitter_pct
<counter>_median
sim_maintenance_estimated_cycles
sim_pages_visited, sim_payload_reads, sim_outputs, ...
```

Cycle conversion:

```text
hw_cycles = maint_ms * freq_mhz * 1000
```

For the current 134 MHz xclbin:

```text
hw_cycles = maint_ms * 134000
```

## Analysis Model

The analysis is empirical, not cycle-accurate. It fits and scores features such
as:

```text
batch_edges
target_level
source_count
persisted_median
l0_partitions_written_median
l0_pages_epoch_stamped_median
cold_page_ids_written_median
cold_pages_visited_median
cold_bits_inspected_median
cold_rows_entered_median
cold_payload_reads_median
cold_refill_stalls_median
cold_merge_inputs_median
cold_outputs_median
sim_maintenance_estimated_cycles
```

The intended model family is:

```text
hw_cycles =
  base
+ a * batch_edges
+ b * pages_visited
+ c * bits_inspected
+ d * payload_reads
+ e * refill_stalls
+ f * outputs
```

The first useful result is not the exact coefficient value. The first useful
result is which feature families explain the HW cycle trend and where the
simulator is structurally undercounting.

## Acceptance Criteria

Phase 2B is accepted if:

- The dry-run emits the 19-case matrix and 57 commands with `--repeats 3`.
- All planned HW cases run or failures are explicitly recorded.
- Every successful case has raw stdout/stderr and command logs.
- `runs.csv` and `summary.csv` are generated.
- `maint_ms` is converted to HW cycles at the selected frequency.
- The analyzer generates `analysis/summary.csv` and `analysis/fit.json`.
- The summary merges simulator structural counters unless `--skip-simulator`
  is deliberately used for a quick iteration.
- The fit report identifies dominant timing features and unstable outliers.
- Most stable points should be explainable within roughly 30%-40% error before
  claiming the empirical model is useful.

## Claims Allowed After This Phase

Allowed:

```text
We measured B-stage maintenance timing on existing HW across controlled
microbenchmarks, repeated each point three times, and identified which exported
maintenance counters best explain the extra HW cycles.
```

Not allowed:

```text
The simulator is cycle-accurate.
The absolute HW time is predicted within final paper-quality error.
The D-stage SSSP/end-to-end path is calibrated.
The AXI/HBM/AXIS stream behavior is fully modeled.
```
