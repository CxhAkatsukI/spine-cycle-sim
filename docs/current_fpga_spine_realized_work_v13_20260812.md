# Current-FPGA Spine Realized-Work Timing v13

## Why v13 exists

The immutable v12 one-scale model passed correctness, structural-work, and
memory-ledger checks but failed its WK/R19 Spine timing holdout.  Median total
cycle errors were 40.23% for weighted SSSP, 27.57% for CC, and 31.02% for
residual PageRank.  The failed v12 evidence remains unchanged under:

```text
/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812/
```

The failure is not an algorithmic-work mismatch.  Routed FPGA and simulator
rounds, range tasks, and processed edges match exactly for SSSP and CC.  The
v12 timing map instead assumes one graph-independent scale for all reader and
compute work.  WK, for example, services 1,167 SSSP edges in six range tasks,
whereas R19 services only 21 edges in 20 range tasks.  One scale cannot preserve
both routed timings.

## Frozen model

V13 retains the v12 execution image and profiles.  It changes only the timing
map to use work emitted by the execution-driven simulator:

```text
reader = c_round * rounds + c_edge * processed_edges
compute = c_round * rounds + c_task * range_tasks + c_edge * processed_edges
iterative_span = c_round * rounds + c_task * range_tasks + c_edge * processed_edges
total = calibrated_maintenance + iterative_span
```

Residual PageRank rows with zero device propagation rounds use maintenance as
their complete routed dynamic-kernel window.  Reader and compute event
intervals overlap and are never added together.

The model is shared by SSSP and CC because both routed xclbins instantiate the
same owner-FIFO reader/compute structure.  AU, SU, WK, and R19 are calibration
datasets in v13 because WK/R19 were inspected while diagnosing v12.  PK and
LJ08 were hash-pinned and had no v13 result before freeze; they are the
independent holdout.  SO and LJ are stress validation only.

Calibration errors before holdout execution are:

| Component | Median absolute error | Maximum absolute error |
|---|---:|---:|
| Reader | 12.47% | 23.83% |
| Compute | 2.24% | 6.80% |
| Iterative span | 13.08% | 23.96% |

## Reproduce the freeze

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3
python3 -m unittest \
  tests.test_current_fpga_calibration \
  tests.test_current_fpga_spine_realized_work_v13 \
  tests.test_current_fpga_spine_compacted_matrix
python3 scripts/freeze_current_fpga_spine_realized_work_v13.py
```

Frozen evidence is in:

```text
docs/evaluation_refresh_20260810/calibration_v13_frozen/
```

Run the independent holdout only after the freeze is committed:

```bash
python3 scripts/run_current_fpga_spine_compacted_matrix.py \
  --simulation-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v13_20260812 \
  --lib-dir cpp/sst/build/sst-current-fpga-v12 \
  --dataset pk --dataset lj08 \
  --jobs 2 --memory-reserve-gib 64
```

No PK/LJ08 row may be used to alter the frozen coefficients.  A failed holdout
must remain failed and requires a new contract version for any subsequent
mechanism repair.
