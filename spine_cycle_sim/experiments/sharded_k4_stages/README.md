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
| `sst_candidate.py` | Strict explicit v1/v2/v3 profile selection, memory and owning-HLS header admission |
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

CLI files under `scripts/` parse arguments and delegate here. Numerical HLS
changes belong to `grasu-regraph-integration`. The distinct routed SST candidate
uses `RoutedReGraphSystem`; these runners do not replace the legacy v8 probe.
Original-paper reproduction, resource-matched
A4, old K4 and optimized K4 remain distinct evidence boundaries.
