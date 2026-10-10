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
| `bitstream.py` | Routed timing, clock and normalized XRT connectivity admission |
| `comparison.py` | Alternating original/candidate board runs with identical host/input |
| `delivery.py` | Frozen initial diagnostic package; never replace its raw evidence |
| `optimization_delivery.py` | Immutable pre-route raw evidence, including failed RTL attempts |

CLI files under `scripts/` parse arguments and delegate here. Numerical HLS
changes belong to `grasu-regraph-integration`; the production simulator is
not changed by these runners. Original-paper reproduction, resource-matched
A4, old K4 and optimized K4 remain distinct evidence boundaries.
