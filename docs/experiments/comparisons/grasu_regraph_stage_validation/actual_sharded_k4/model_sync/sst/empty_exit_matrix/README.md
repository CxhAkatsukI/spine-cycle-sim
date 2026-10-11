# Real-Graph Empty-Exit Validation

## Decision

All six AU/SU/WK old/optimized adapter cases preserve the complete FPGA
result, resident input, convergence and non-timing ledgers. Every v3 replay
also reproduces its previous serialized result byte for byte. The v4 runs
reuse the plugin already admitted by the [focused control](../empty_exit_model/README.md);
no further numerical source, model coefficient or memory setting changed.

**This is a functional pass and a timing diagnostic, not a complete timing
calibration or an original-A4 performance match.** Close total spans on
some rows do not establish each stage's accuracy. WK's optimized path still
has a substantial mismatch, retained below rather than fitted away.

## Complete Matrix

Times are milliseconds at 150 MHz. The FPGA column uses the predeclared
first repetition of each arm, not a selected best repetition. Signed
difference is `100 * (prediction / board_span - 1)`.

| Graph | Adapter | Predicted resident compute | FPGA compute span | Signed difference |
| --- | --- | ---: | ---: | ---: |
| AU | Original | 2,076.570 | 2,053.708 | +1.11% |
| AU | Optimized | 192.798 | 200.395 | -3.79% |
| SU | Original | 3,429.049 | 3,382.743 | +1.37% |
| SU | Optimized | 390.491 | 395.824 | -1.35% |
| WK | Original | 5,740.279 | 5,670.419 | +1.23% |
| WK | Optimized | 60.164 | 92.622 | -35.04% |

These windows are not identical. The model excludes XRT dispatch, same-CU
relaunch and inter-round host gaps. The board compute span includes gaps
between the first compute start and final compute completion. Modeled
addresses are deterministic offsets, not captured physical BO addresses.
Neither overlapping kernel lifetime nor total-span agreement is an
exclusive component counter.

The exact geometry and initial-state contract is unchanged from the
[first SST checkpoint](../README.md): AU has 515,281 vertices and eight
shards, SU 567,316 and nine, WK 1,140,149 and eighteen. AU/SU execute two
resident update rounds; WK executes one. Old and optimized arms consume
the same PMA, old converged state and update-active input. This experiment
changes the empty-row helper timing, not the problem or useful work.
The 73-clock correction applies to every visited empty row, including
empty rows before the last occupied source in either arm. The optimized
arm still skips the trailing empty rows; internal empty rows are not free.

## What The Invocation Trace Shows

[invocation_timing.json](invocation_timing.json) aligns every adapter and
whole `lksg` invocation by round, partition and worker. For optimized WK,
worker 0 processes partitions 0, 4, 8, 12 and 16. The board has four
inter-invocation adapter gaps of approximately 9.084, 7.740, 7.478 and
3.413 ms, totalling 27.714 ms on this worker. The predictive simulator
starts each successor immediately.

For context, the first adapter invocation on each WK worker has the
following lifetime. These overlap and include downstream backpressure;
the table is not an exclusive-stage calibration.

| Worker | First partition | Model lifetime, ms | FPGA lifetime, ms |
| ---: | ---: | ---: | ---: |
| 0 | 0 | 56.231 | 59.940 |
| 1 | 1 | 55.123 | 54.820 |
| 2 | 2 | 54.789 | 54.367 |
| 3 | 3 | 55.064 | 54.393 |

Those successor commands were already queued before the preceding adapter
completed, but their recorded submission occurs later. This is evidence of
a runtime/dependency scheduling difference, not proof that graph preparation
was late or that every gap is CPU execution. Other workers overlap; their
gaps must not be summed into an E2E penalty. Subtracting this worker's gap
from the total mismatch would also not establish a calibrated model.

The [occupied-row RTL probe](../occupied_row_rtl/README.md) separately
checks the helper schedule under controlled responses and backpressure.
The empty-call 73 clocks must not simply be appended after every occupied
row's final packet. No measured gap or fitted multiplier was injected into
the model to obtain this report.

## Evidence And Reproduction

The immutable [matrix report](matrix.json), [raw index](matrix_raw_index.json)
and `raw_matrix.tar.gz` contain twelve runs, all six parent v3 results,
complete state outputs, board logs, profiles, identities and resource logs.
Large resident fixtures and the common plugin are linked through the
unchanged dependency packages rather than duplicated. The archive excludes
`resident.bin`; each run's input hash is retained and checked against the
prior run before sealing. The invocation report is reproducible analysis of
this archive, not an additional model run.

The experiment owner is `sharded_k4_stages/row_exit_matrix.py`; trace
analysis is separately owned by `invocation_timing.py`. Numerical runs use
at most two workers, 8 GiB per child, a 16 GiB reserve, CPU affinity 112--113,
a 1,800-second case timeout and a one-billion-cycle cap. Simulator wall
time is not modeled device time. Recorded `wait4` peak RSS is per process,
not the simultaneous process-tree total.

The completed outer v3 replay took 858.95 seconds and the v4 matrix
1,579.09 seconds. Maximum recorded process RSS was 637,904 KiB, about
623 MiB; neither matrix timed out. All 149 focused `test_sharded_k4_*`
Python tests, 15 repository-structure tests and 23 CTest targets pass.
The CTest replay reused the existing frozen Release core build rather
than rebuilding or overwriting the campaign plugin. Documentation/catalog
and whitespace checks pass. Protected figure/calibration files, the
installed default plugin and the production HLS worktree are unchanged.

Replay both `configs/experiments/sharded_k4_routed_sssp_timing_v3.json` and
`sharded_k4_routed_sssp_timing_v4.json` with
`scripts/run_routed_k4_timing_matrix.py`, the common pinned plugin, owning-HLS
fixture exporter and fresh output directories. Exact commands and input
paths are in the archived outer `*.resources.json`. Sealing through
`package_real_matrix(root, campaign, output)` requires the campaign binding,
unchanged numerical sources and both complete matrices. It refuses to
overwrite an existing package.

Portable checks from the repository root:

```bash
python3 -m unittest tests.test_sharded_k4_row_exit_matrix \
  tests.test_sharded_k4_row_exit_matrix_package \
  tests.test_sharded_k4_invocation_timing \
  tests.test_sharded_k4_invocation_timing_package
```

The checks rederive results from raw evidence and verify all archive and
dependency hashes. They do not silently rerun FPGA or SST experiments.

## Remaining Work

The real-graph replay gate is closed; whole-path timing remains open.
Distinguish dispatch/dependency gaps from device completion and transport
behavior before admitting a common timing window. The final original-A4
comparison additionally needs matched algorithm arithmetic, resident state,
round count, clock, resources and memory model. Existing original-A4
fixed-point PR controls and this routed SSSP matrix cannot be divided to
claim an integration speedup. Paper figures and prior evidence are unchanged.
