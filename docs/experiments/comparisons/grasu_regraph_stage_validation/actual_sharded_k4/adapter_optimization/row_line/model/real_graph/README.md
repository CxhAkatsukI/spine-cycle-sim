# Whole-Line Resident-Graph Matrix

This extends the [small-fixture model checkpoint](../README.md) with the
complete, pinned AU/SU/WK resident SSSP fixtures from the prior
[real-graph matrix](../../../../model_sync/sst/empty_exit_matrix/README.md).
It uses the actual adapter model, not the independent original-A4 reader.
No historical evidence, measured bitstream, paper or figure is replaced.

## Scope And Result

Both arms already use prefetch and stop after the last occupied source;
both omit the historical empty-helper wait. The reference is that
**unrouted skip-empty implementation**, not original ReGraph A4 or the old
routed baseline. Only the candidate enables whole-line directory reads.
Its explicit profile is `grasu_regraph_row_line_sssp_compute_v1` on the
pinned dedicated-source topology. Timing parameters, PMA layout, queues,
backend and memory service remain unchanged; no timing factor is fitted.

| Case | Vertices | Destination partitions | Convergence rounds | Live edges per round | PMA slots |
| --- | ---: | ---: | ---: | ---: | ---: |
| AU | 515,281 | 8 | 2 | 390,855 | 1,843,296 |
| SU | 567,316 | 9 | 2 | 616,126 | 2,625,456 |
| WK | 1,140,149 | 18 | 1 | 1,142,360 | 2,727,664 |

These are the preserved logical fixtures, including padding and full
destination partitions, not newly reduced slices. Their inherited inputs
contain the updated PMA, old converged values and update-active payload.
The complete value oracle comes from the previous checked fixture; this
study checks its hash and every output byte, not a newly computed independent
Dijkstra oracle. The graph set/order, geometry and input/output hashes are
fixed by `row_line/model_scope.py`; partial or substituted matrices fail.

All six executions pass complete external-state equality, identical work and
round activity, independent directory/PMA/source/publication accounting,
and backend/arbitration drainage. Results are **simulator predictions**, not
new FPGA measurements or per-stage calibration.

| Case | Directory requests, reference -> candidate | Directory bytes, reference -> candidate | Predicted total cycles, reference -> candidate | Cycle reduction |
| --- | ---: | ---: | ---: | ---: |
| AU | 1,268,368 -> 158,560 | 81,175,552 -> 10,147,840 | 15,479,318 -> 15,063,595 | 2.69% |
| SU | 1,950,946 -> 243,884 | 124,860,544 -> 15,608,576 | 25,355,911 -> 24,516,942 | 3.31% |
| WK | 366,938 -> 45,883 | 23,484,032 -> 2,936,512 | 8,745,414 -> 8,621,421 | 1.42% |

The approximately 8x directory-traffic reduction does **not** imply an 8x
compute speedup. Under this unchanged model, other work and overlapping
execution limit the total benefit to 1.42--3.31%. This is an incremental
whole-line change on an already optimized input path; the earlier skip-empty
FPGA improvement is a separate experiment. This matrix neither proves a
specific remaining hardware bottleneck nor resolves the original-A4 gap.

The measured boundary is resident adapter/ReGraph computation through its
modeled completion. GraSU update, initial migration, host preprocessing and
orchestration are outside it. These numbers cannot be used as full G+R
update-to-result or setup-inclusive speedups.

## Review And Reproduction

The implementation remains in one existing package:
`spine_cycle_sim/experiments/sharded_k4_stages/row_line/`.
`model_scope.py` owns separate immutable smoke/resident bounds and matrix
identities; `model_study.py` freezes and executes; `model_validation.py`
recomputes geometry and traffic; `model_recheck.py` rechecks complete raw
evidence; `model_delivery.py` seals and verifies it. The old smoke bounds
and its portable archive are unchanged. Production HLS stays in the
integration repository.

From the simulator worktree root, portable verification requires no original
experiment paths, compilation, SST run or FPGA:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_delivery \
  --destination docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/model/real_graph/evidence \
  --verify-only
python3 -m unittest discover -s tests -p 'test_sharded_k4_row_line_model*.py'
```

To rerun with the preserved local dependencies, choose a fresh output:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_study \
  --scope resident_matrix_v1 \
  --plugin /data/chuxiao/experiments/sharded_k4_row_line_model_20261011/plugin \
  --fixture /data/chuxiao/experiments/sharded_k4_empty_exit_matrix_20261011/matrix_v4/au_candidate \
  --fixture /data/chuxiao/experiments/sharded_k4_empty_exit_matrix_20261011/matrix_v4/su_candidate \
  --fixture /data/chuxiao/experiments/sharded_k4_empty_exit_matrix_20261011/matrix_v4/wk_candidate \
  --output /data/chuxiao/experiments/fresh_row_line_resident_matrix
```

Each arm runs serially at affinity 112-113, with a 180-second timeout,
100-million-cycle cap, sampled 3-GiB process-tree RSS budget and live 16-GiB
host reserve. The resident-only inventory limits are 2 million vertices and
256 MiB per fixture; they do not relax the separate smoke limits. Across six
SST runs, wall time totals 105.36 seconds, peak sampled tree RSS is 602.34 MiB
and minimum available host memory is 52.83 GiB. Watchdog cleanup succeeds in
all runs. This is sampled process monitoring, not cgroup containment.

## Evidence And Remaining Gates

The [results](evidence/results.json), [file index](evidence/verification.json)
and [raw archive](evidence/raw_model.tar.gz) contain 637 indexed files,
33,637,742 compressed bytes and 451,846,121 uncompressed bytes. Archive SHA-256:
`46373c3c1ace0c42429651594b39910e28999c192afc95cac79fd4fe42466c9e`.
They preserve the executed numerical source snapshot, profiles, full fixtures,
expected/actual values, complete JSON counters, logs, resource records and
isolated plugin. SST, DRAMSim3 and toolchains are indexed dependencies, not
redistributed. Source/plugin/input changes fail rather than silently retime
the study. Subsequent documentation and extra delivery tests are not claimed
to have existed inside the numerical-run source freeze.

The isolated plugin is unchanged from the small-fixture checkpoint:
`e167eb73b4a69c59f370734c08f7af7e682788c942178b42228d9db61a4b7fa2`.
That checkpoint's 27 core executables and five byte-exact legacy SST cases
remain the build/compatibility gates; they are not new hardware evidence.
The default SST plugin is not replaced.

All 298 sharded-K4 Python tests pass, including both portable archives,
complete-matrix enforcement and rejection of changed bounds or scope.
The later [regression report](evidence/regression.json) and
[logs](evidence/raw_regression.tar.gz) are separate from the numerical-run
archive. The 15 repository-structure tests and document-layout checks also
pass. Regression peak sampled tree RSS is 1.97 GiB, below its 3-GiB budget.

The whole-line XO has compile/ABI/RTL admission but remains unrouted. New
paired FPGA timing, candidate calibration and an algorithm/state/window-
matched original-A4 comparison remain open. Route admission keeps its
40-GiB tree budget plus 16-GiB reserve; this study does not lower it or claim
a queued route has completed. The overall validation objective is ongoing.
