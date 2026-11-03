# Verification Report

## Fresh Executions

- 42/42 declared cases pass their runner correctness gate; zero timed-out
  processes and zero nonzero execution exit codes in the admitted campaign.
- The 25 carry-history fixtures use their fixture/carry validation contract.
  The other 17 cases require zero architecture and mathematical mismatches.
  Fixture validation must not be described as an independent full-graph
  algorithm oracle on all 42 rows.
- All 11 selected Figure 10 rows have closed ten-stage and total ledgers.
  Ten-stage sums equal total cycles, and grouped percentages sum to 100%.
- All 41 Figure 11 rows are new observations from the same identified plugin.
  The 24/17 calibration/holdout split is frozen from the predecessor's case
  roles; zero-net remains excluded from fitting. All numerical coefficients
  and per-stage regression diagnostics are recomputed.
- Execution wall-time sum: 1,404.67 s, not accelerator cycles. Maximum
  `wait4` process peak RSS: 19,146,624 KiB (18.26 GiB), observed on R19 CC.
  This is maximum-process RSS, not a simultaneous process-tree measurement.
- Serial execution, inherited 32-GiB per-process address-space limits,
  24-GiB prelaunch available-memory reserve, 1,200-second timeout per case.
  R19 CC completed in 928.02 s without reducing its input or semantics.

The initial retained preflight used generic rather than carry-fixture
validation and failed. It is archived separately and is not a fitted row.
A subsequent successful carry smoke lacked a raw `vertices` field expected
by the new packaging wrapper. The wrapper now reads the unchanged input
header when that field is absent. Its successful raw result was revalidated
under the same frozen plugin, not replaced or edited. The final status file
retains `PASS_REVALIDATED_UNCHANGED_RAW` for that row.

Final packaging also corrected the derived admission wrappers: they now
name their validation contract and omit unavailable architecture/mathematical
mismatch fields on carry fixtures instead of filling them with zero. The
superseded wrappers are retained in a separate archive. Raw simulator
outputs, their hashes, cycles and the calibration/holdout split are unchanged.
CSV serialization uses LF line endings without changing values.

## Automated Checks

From the repository root:

```bash
python3 -m unittest tests.test_realized_work_refresh \
  tests.test_rq3_realized_work tests.test_rq3_calibration_projection
python3 -m unittest tests.test_repository_structure
python3 scripts/audit_repository_structure.py --check-docs
python3 scripts/audit_repository_structure.py --check-catalogs
git diff --check
python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.verify \
  --package docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_handoff_20261103 \
  --repository .
```

The focused numerical-analysis/packaging tests pass (33), as do the
organization tests (15). The verifier checks the exact manifest file set,
file hashes, archive part/member hashes, existing Figure 8--9 capsule hashes,
24 FPGA ratios, Figure 8 one-batch semantics and ratios, nine Figure 9
traffic/energy ratios, stage conservation, normalization and fit split.
Organization/catalog/whitespace gates pass. A successful verifier result is
integrity/admission evidence, not evidence that a model's prediction error
is small.

The numerical engine is unchanged by this delivery. A fresh production SST
plugin build and the complete 42-case execution are the integration checks;
the unrelated full C++ core suite and FPGA routing/board runs were not
repeated in this data-packaging task. Figure 7 uses the archived October 26
board runs rather than claiming new November board measurements.

## Remaining Limits

- Real-input holdout median/max APE remain 58.08%/89.07%; this is not a
  precise predictor on every real input despite high aggregate R2.
- No new FPGA stage calibration; regression coefficients do not calibrate
  the simulator's timing engine.
- Dense SST residual Apply is distinct from the separate sparse candidate.
- Figure 7 cached G, Figure 8 shared-metadata G and Figure 10--11 SST are
  different documented configurations, not one common architecture identity.
- No new ten-batch measurement, current FullPR matrix, or original-publication
  G/R reproduction is established. Original Figure 8--9 baseline-admission
  limitations are not removed by repackaging.
- Figure 9 fixed-threshold AU/SU/WK cases have zero nonempty propagation;
  positive/negative nonempty follow-ups are supplied separately.
- No paper edits or new plot-rendering validation are claimed; this is the
  requested data delivery.
