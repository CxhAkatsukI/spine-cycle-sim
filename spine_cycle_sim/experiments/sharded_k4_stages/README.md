# Actual Sharded-K4 Study Code

This package owns the actual routed K4 study, not the independent original-A4
PMA timing control. Start with the
[experiment guide](../../../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/README.md).

| Module | Responsibility |
| --- | --- |
| `execution.py` | Frozen three-arm host-instrumentation diagnostic |
| `board.py` | Shared board lease, occupancy guard and production host arguments |
| `analysis.py` | Event identity, dependencies, interval union and concurrency |
| `synthesis.py` | Four default-off adapter flag ablations and structured HLS reports |
| `rtl.py` | Source-pinned baseline/candidate RTL co-simulation |
| `routing.py` | Single-XO ABI gate, lossless connectivity config and link preparation |
| `link_runtime.py` | Route-specific aggregate RSS, memory reserve and timeout watchdog |
| `process_cleanup.py` | pidfd-bound cleanup of observed descendants across nested sessions; not cgroup containment |
| `route_recovery.py` | Completed-artifact recovery after supervisor loss, with incomplete monitoring explicit |
| `bitstream.py` | Routed timing, clock and normalized XRT connectivity admission |
| `comparison.py` | Alternating original/candidate board runs with identical host/input |
| `delivery.py` | Frozen initial diagnostic package; never replace its raw evidence |
| `optimization_delivery.py` | Immutable pre-route raw evidence, including failed RTL attempts |
| `board_delivery.py` | Raw-log revalidation and a separate immutable routed/paired-board package |
| `model_adapter.py` | Finite adapter and production-HLS shared-fixture checks; no timing admission |
| `model_delivery.py` | Exact legacy regression and adapter-component evidence package |
| `compute_delivery.py` | Compute extraction and finite shared-port evidence; not candidate system timing |
| `model_frontend.py` | Connected Scatter/source gates; distinguish measured XO from later HLS worktree |
| `frontend_delivery.py` | Binary-source, finite frontend and unchanged-legacy evidence package |
| `model_system.py` | Complete SSSP candidate state, schedule and conservation gates; not hardware timing |
| `system_delivery.py` | Immutable complete-candidate and exact legacy SST evidence package |
| `sst_candidate.py` | Strict explicit routed v1-v4 and unrouted whole-line/cross-row profile selection, memory and owning-HLS header admission |
| `sst_timing.py` | One bounded HLS-export/SST run, full FPGA-result comparison and explicit nominal timing limits |
| `sst_campaign.py` | Complete predeclared old/new matrix, at most two memory-admitted workers, retained failures |
| `sst_input_audit.py` | Independent bounded synchronous old-state/active oracle and empty-tail inventory |
| `sst_delivery.py` | Immutable six-row SST/board evidence, common-source legacy gate and nominal tail diagnostics |
| `completion_delivery.py` | Separate capped-state and isolated read/write-blocking evidence; no model change or timing admission |
| `channel_delivery.py` | Independent-channel correction: exact v1 replay, full v2 state/traffic gates and a separate immutable package; never upgrades nominal timing to calibration |
| `row_sweep.py` | Predeclared four-size empty-row control using unchanged old/new FPGA bitstreams and the fixed v2 plugin |
| `row_sweep_analysis.py` | Live-prefix/PMA/state invariants and descriptive incremental slopes; no parameter fitting |
| `row_sweep_delivery.py` | Revalidate all 24 board / eight model outputs and freeze a portable raw package with explicit dependencies |
| `stream_contract.py` | Verify all 19 compute-stream connections and FIFO capacities against both pinned routed block designs |
| `stream_delivery.py` | Exact v2 replay, unchanged full results/traffic, and separate v3 stream-depth evidence; no timing fit |
| `row_exit_contract.py` | Pin both generated RTL helpers and their handshake tests; verify the measured 73-cycle empty-row exit |
| `row_exit_sweep.py` | Replay the existing four-size board control with exact v2 and explicit v4 predictions; no new FPGA runs or fitting |
| `row_exit_delivery.py` | Seal the focused empty-exit correction and its old-result gates; keep real-graph and A4 validation pending |
| `row_exit_matrix.py` | Seal full v3/v4 real-graph replay with unchanged work and numerical sources; retain timing mismatches |
| `segment_schedule.py` | Pinned occupied/empty helper RTL probes with controlled responses and backpressure; not HBM timing |
| `segment_schedule_delivery.py` | Seal both twelve-case RTL traces and retain failed testbench attempts separately |
| `invocation_timing.py` | Align all adapter/lksg invocations and same-CU gaps from frozen evidence; never sum overlapping gaps or fit model delays |
| `dispatch_sweep.py` | Rotating, bounded CPU-affinity control with unchanged admitted host/bitstream and complete-result checks |
| `dispatch_delivery.py` | Revalidate all nine dispatch runs and seal logs/identities; retain the negative result without claiming a runtime root cause |
| `dispatch_trace.py` | Unprofiled/profiled XRT trace control with fixed host, input, bitstream and complete outputs |
| `runtime_trace.py` | Structured VTF parsing, unique kernel-event alignment and compute-window transfer dependencies |
| `input_residency.py` | Rotating frozen/off/on host control; initial migration separately charged and profile kept diagnostic |
| `residency_matrix.py` | All six fixed-model rows on FPGA after initial residency, three repetitions and no fitting |
| `residency_validation.py` | Recompute all 30 raw attempts, complete results, unchanged model predictions and transfer findings |
| `residency_delivery.py` | Separate immutable input-residency archive, source snapshots and complete-output identities |
| `empty_segment/` | Paired C/RTL empty-helper controls, effective compile-contract checks and immutable evidence delivery; no timing-model change |
| `adapter_axi/` | Full production-XO external AXI probe, exact routed-version binding, conservation analysis and portable evidence delivery; synthetic memory, not board timing |
| `row_line/` | Explicit whole-line HLS candidate, padded-host equivalence and portable evidence. `model_contract.py` owns the distinct unrouted profile, `model_scope.py` pins separate smoke/real-graph matrices and limits, `model_study.py` owns bounded SST replay, `model_validation.py` independently checks fixture geometry/traffic, `model_recheck.py` rechecks preserved raw evidence, and `model_delivery.py` seals/verifies the portable checkpoints; no route or FPGA timing admission. |

CLI files under `scripts/` parse arguments and delegate here. Numerical HLS
changes belong to `grasu-regraph-integration`. The distinct routed SST candidate
uses `RoutedReGraphSystem`; these runners do not replace the legacy v8 probe.
Original-paper reproduction, resource-matched
A4, old K4 and optimized K4 remain distinct evidence boundaries.

Within `row_line/cross_row/`, `model_contract.py` owns strict profile and
synthesis-identity admission. `model_study.py` and `model_delivery.py` select
the shared bounded resident runner and conservation/portable recheck gates;
`model_timing.py` compares all twelve logical RTL shapes without fitting,
and `model_timing_evidence.py` rechecks those preserved inputs and outputs.
`model_checkpoint.py` packages exact legacy equivalence, complete core tests
and the timing diagnostic. Shared safe extraction belongs to
`row_line/model_archive.py`, not each delivery CLI. Start with the
[cross-row model guide](../../../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/cross_row/model/README.md).

`row_line/cross_row/a4_control/` owns the separate original-A4/whole-line/
cross-row resident-round control. Its contract, preparation, execution,
analysis, raw recheck and portable delivery remain separate responsibilities;
the [control guide](../../../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/cross_row/a4_control/README.md)
retains the negative timing prediction and explicit resource/window limits.
It does not alter the previous whole-line control or its validator.

Within `row_line/`, `route_preparation.py` binds the checked production XO,
padded SSSP host and unchanged historical kernels/connectivity; `route.py`
composes the existing environment, admission and link owners. Its separate
[route checkpoint](../../../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/route/README.md)
records a successful environment preflight and memory-refused non-start,
not routed timing or an FPGA speedup.

`row_line/cross_row/route_preparation.py` independently admits the V3 XO,
unchanged ABI/connectivity and checked padded host against an immutable
whole-line basis. Its thin `route.py` uses `row_line/route.py::run_prepared`
and the existing environment, admission and link owners. The
[V3 route checkpoint](../../../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/cross_row/route/README.md)
preserves the memory-refused non-start; no new route supervisor, simulator
timing factor or FPGA claim is introduced.
