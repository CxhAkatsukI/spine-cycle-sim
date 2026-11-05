# Fresh Realized-Work Campaign

This package owns the data-only Figures 7--11 handoff. It does not change
the simulator's numerical implementation, the paper, or historical evidence.

| Module | Responsibility |
| --- | --- |
| `matrix` | Freeze the historical 41-row split, one extra zero-net, and derived profiles |
| `run` | Execute bounded processes; admit correctness and frozen plugin/input identities |
| `receipts` | Admit explicit failed-case retries with unchanged implementation, workload, profile and split |
| `analysis` | Recompute absolute/normalized stages and a calibration-only cost-model fit |
| `delivery` | Collect current FPGA/simulator evidence and archive fresh raw outputs |
| `verify` | Check hashes, archive membership, stage conservation and data coverage offline |

Run each CLI with `python3 -m
spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.MODULE
--help`. Full commands and the actual results are in the
[data handoff](../../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_handoff_20261103/README.md).

`matrix` reads only identities and roles from the old Figure 11 CSV. It never
uses its observed cycles or fitted predictions. The matrix and plugin are
frozen before the first admitted execution. Fig. 10 is an overlap-aware
simulator stage prediction, not a per-stage FPGA calibration. Fig. 11 fits
only the predeclared calibration rows; all holdouts remain out of fitting.

Safety defaults are one process at a time, a 32-GiB child address-space
limit, a 24-GiB available-memory reserve, and a 1,200-second case timeout.
Inputs, profiles, raw results and failed preflight evidence are retained.
The fresh numerical-core plugin must be built in a separate directory.

`run --memory-gib 8` can reduce the finite child limit; the limit is part of
the campaign identity. To retry a memory-limited case, use a **new** output
directory with `--only CASE --memory-gib 16`. Compose it with
`analysis --campaign ORIGINAL --replacement-campaign RETRY --output NEW`.
The implementation, inputs, derived profile and fit role must be unchanged.
Only a previously failed case can be replaced. The failed campaign is not
rewritten, and `measurement_origins.json` identifies every selected receipt.

Focused tests: `python3 -m unittest tests.test_realized_work_refresh`.
