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

CLI files under `scripts/` parse arguments and delegate here. Numerical HLS
changes belong to `grasu-regraph-integration`; the production simulator is
not changed by these runners. Original-paper reproduction, resource-matched
A4, old K4 and optimized K4 remain distinct evidence boundaries.
