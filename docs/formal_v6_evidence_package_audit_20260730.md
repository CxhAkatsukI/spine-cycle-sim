# Formal-v6 evidence-package audit (2026-07-30)

The formal-v6 report refresh ends with a fail-closed package audit:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
bash scripts/refresh_formal_v6_report.sh
```

The standalone equivalent is:

```bash
python3 scripts/audit_formal_v6_evidence_package.py
```

The machine-readable result is
`docs/paper/data/formal_v6_primary/evidence_package_audit.json`.

## Minimum first-package gates

The command exits nonzero unless all of the following hold:

1. Every observed formal execution has closed individual correctness,
   backend arbitration, backend traffic, DRAM request, and component-activity
   ledgers. The execution IDs in `system_rows.csv` and
   `component_activity.csv` must match exactly.
2. Every plotted pair maps back to a complete cross-system correctness group
   with a matching final state.
3. Weighted SSSP, connected components, and thresholded residual PageRank form
   complete Spine/K4-shared pairs on at least three real datasets.
4. The AskUbuntu update-only matrix contains insertion, deletion, and weight
   change at batch sizes 1, 8, and 64.
5. The five RQ3 classes (zero net, shallow insertion, deep carry, PageRank
   correction, and deletion fallback) each have an eligible execution.
6. The all-row carry, physical resolve/apply, seed, and drain/sync regressions
   each have `R^2 >= 0.99`.
7. The report PDF and the required primary, memory, update, and RQ3 SVG figures
   exist and are nonempty.

The committed snapshot passes these minimum gates with 26 audited executions,
9 complete pairs across AskUbuntu, SuperUser, and WikiTalk, 165 component rows,
all 9 update points, and all 5 RQ3 classes.

## Full-matrix boundary

`minimum_package_status=PASS` does not imply that the frozen formal matrix is
complete. `full_matrix_status` is independently `PASS` only when the primary
analysis reports no missing execution IDs. The current snapshot remains
`PARTIAL` at 26 of 36 expected executions. Missing rows are either active or
policy-stopped after a recorded wall-time feasibility decision. A row must
complete or receive a declared scope exclusion before the full matrix can be
called complete; partial counters never enter performance aggregates.

For a release that requires every runnable formal-v6 execution, use:

```bash
python3 scripts/audit_formal_v6_evidence_package.py --require-full
```

That command intentionally fails while any formal execution is unfinished or
policy-stopped without a declared scope exclusion.
