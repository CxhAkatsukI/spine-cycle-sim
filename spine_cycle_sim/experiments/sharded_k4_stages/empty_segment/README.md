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

Run these owners through `python3 -m ...empty_segment.MODULE --help`.
Use fresh run and evidence paths; never replace a prior package. The v1 guard
and v2 extracted helper use different frozen source bytes. The delivery owner
checks each against its own snapshot, not against today's checkout.

`GRASU_REGRAPH_SKIP_EMPTY_SEGMENT` remains default-off in the integration
repository. Source tests and C/RTL latencies do not admit FPGA, HBM or A4
timing. Route, paired board tests and a separate model candidate remain open.
