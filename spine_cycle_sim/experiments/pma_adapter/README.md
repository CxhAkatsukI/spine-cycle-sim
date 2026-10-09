# Finite PMA / Original A4 Control

This package owns the finite adapter-input experiment. It is separate from
the frozen source-functional adapter package and from the production SST
model. Timing prediction is not FPGA calibration or publication matching.

| Responsibility | Module |
| --- | --- |
| Admitted input preparation and old-source preservation | `preparation.py` |
| Lowered HLS access evidence | `schedules.py` |
| Real-source hot/cold/stale-copy conformance and UBSan build | `conformance.py` |
| Exact legacy A4, matched A4 and finite PMA/R execution | `study.py` |
| Aggregate-memory admission and bounded case concurrency | `execution.py` |
| Complete state, traffic, stage-window and overhead checks | `analysis.py` |
| Immutable raw/indexed result delivery | `delivery.py` |

The CLI is `scripts/run_pma_regraph_control.py`. The C++ input component lives
in `cpp/include/spine_sim/pma_adapter/` and `cpp/src/pma_adapter/`; graph wiring
reuses `ComputeWiring<InputSource>` rather than a second downstream model.
