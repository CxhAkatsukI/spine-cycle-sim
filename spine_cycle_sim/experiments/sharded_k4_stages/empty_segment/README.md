# Empty-Segment Study Owner

This package validates the production HLS empty-helper bypass. It changes no
numerical simulator code. Read the
[results and acceptance guide](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/empty_segment/README.md)
before using its timings.

| Module | Responsibility |
| --- | --- |
| `study.py` | Source-pinned, bounded sequential HLS arms |
| `analysis.py` | Complete packet traces, per-call latency and synthesis estimates |
| `validation.py` | Recheck frozen historical execution, effective flags and part/clock |
| `delivery.py` | Preserve unsuccessful/effective paired controls as separate raw archives |
| `functional.py` | Freeze, execute and package twelve C++ format/equivalence gates |
| `production.py` | Source-bound production XO compilation and frozen K4 ABI/flag checks; no route |
| `production_validation.py` | Recheck compile resources, exact flags/ABI, snapshots and source bindings |
| `production_delivery.py` | Seal successful production compilations without admitting routed timing |
| `route.py` | Preserve frozen single-XO preparation and memory-admission records |
| `route_delivery.py` | Package a verified admission refusal as a non-start, not a route failure |
| `route_execution.py` | Future route execution with pinned entry point and nonzero failure/refusal exit status |
| `route_environment/` | Fresh route entry point with explicit vendor environment, bounded compatibility smoke, pins and honest memory refusal; leaves frozen wrappers intact |
| `sensitivity/` | Isolated legacy-exact replay and uncalibrated empty-helper timing sensitivity; no production-profile change |

Run these owners through `python3 -m ...empty_segment.MODULE --help`.
Use fresh run and evidence paths; never replace a prior package. The v1 guard
and v2 extracted helper use different frozen source bytes. The delivery owner
checks each against its own snapshot, not against today's checkout.

`GRASU_REGRAPH_SKIP_EMPTY_SEGMENT` remains default-off in the integration
repository. Source tests and C/RTL latencies do not admit FPGA, HBM or A4
timing. Route, paired board tests and a separate model candidate remain open.
The [production checkpoint](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/empty_segment/production/README.md)
passes XO compile/ABI checks, but records a memory-refused route non-start.
The [model sensitivity guide](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/empty_segment/sensitivity/README.md)
defines a separate twelve-run matrix and its complete-state/traffic gates.
Use `python3 -m ...empty_segment.route_environment --help` for future route
attempts; the [environment checkpoint](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/empty_segment/production/environment-admission/README.md)
passes launcher/host-compiler smoke checks but still records a memory non-start.
