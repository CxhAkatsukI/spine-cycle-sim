# Passive Wait Observation

This diagnostic observes the unchanged routed R core; it does not implement
a new schedule or change memory timing. It replays one frozen SSSP round,
not the full convergence experiment.

| File | Responsibility |
| --- | --- |
| `round_probe.cpp` | One-round execution, independent CSR oracle, physical conservation and output export |
| `histogram.hpp` | Bounded, per-cycle wait-mask collection without execution writes |

Run through the pinned Python module
`spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.wait_overlap`.
The [experiment guide](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/r_bank_stream/prefetch_compact/WAIT_OVERLAP.md)
defines the off/on, registration-order and exact-reference gates, interpretation
limits and finite-memory execution command. Do not sum overlapping waits as
stage times or use this one-round probe to admit complete-R performance.
