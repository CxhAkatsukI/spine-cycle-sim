# Original ReGraph Hardware Preflight

This owner audits the original author path before any board launch. It does
not implement a simulator speed factor, program a board, or admit a paper
performance match. The publication A, source A4 and actual adapter/K4 controls
remain separate experiments.

| Module | Responsibility |
| --- | --- |
| `sources.py` | Clean revision and literal reviewed host/device bindings |
| `oracle.py` | Frozen CSR/task gather equality, two explicit fixed-point PR divisor bindings and publication allocation |
| `artifact.py` | Read-only xclbin topology, actual DATA clock and saved timing inspection |
| `study.py` | Fixed six-input audit, bounded extraction and unchanged transitive identities |
| `delivery.py` | Raw recheck and portable metadata/log/source capsule; no promoted hardware claim |
| `checkpoint.py`, `checkpoint.tcl` | Read-only native checkpoint clocks/timing and exact embedded-partial comparison; no altered constraints |
| `checkpoint_run.py` | Independent atomic memory reservation, bounded query and frozen provenance |
| `checkpoint_delivery.py` | Recheck terminal observations and seal a separate metadata/source capsule without admitting hardware timing |

Read the [hardware campaign's original-R checkpoint](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/original_regraph/README.md)
for results and reproduction. The oracle relies on the earlier complete author
layout admission for task scheduling and source-window allocation. It separately
rechecks capture identities, CSR degrees, gather conservation, signed arithmetic
and output bounds. It is one static PR superstep with `arg=0`, not weighted SSSP,
residual PR or convergence. Both bindings are exposed without changing author
device code or claiming that either reproduces the publication's algorithm.

`SYSTEM_METADATA` contains JSON but XRT requires the `RAW` extraction format.
A saved requested-clock timing failure must not be silently treated as a failure
at an automatically reduced bitstream clock. Conversely, an extracted clock
alone does not establish checkpoint/bitstream/timing identity or source equality.

The checkpoint probe uses the same finite-budget admission ledger as routing.
Other FPGA tools do not block it when their full bounded budgets, its 20-GiB
limit, a 24-GiB reserve and an 8-GiB background allowance fit. It requires
cgroup v2 hard/high limits, zero swap and group OOM handling. Its 1,200-second
read-only Vivado query cannot program a board or rewrite the author artifact.
