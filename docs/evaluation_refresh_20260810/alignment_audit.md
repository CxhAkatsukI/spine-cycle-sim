# Evaluation Refresh Alignment Audit

Status: `INCOMPLETE`

## Campaign

- Analysis: `/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen/analysis_partial`
- Summary status: `PARTIAL`
- Observed executions: `11/18`
- Complete pairs: `2/9`
- Paired algorithms: `weighted_sssp`
- Paired datasets: `sx_askubuntu, sx_superuser`

## FPGA Calibration

- Frozen contract valid: `yes`
- `total_cycle`: pass=`false`
  - missing manifest
- `component_cycle`: pass=`false`
  - missing manifest
- `memory_ledger`: pass=`false`
  - missing manifest

## Figures

- `fig7`: aligned=yes, status=`PASS`
- `fig8`: aligned=no, status=`PASS_CURRENT_MODEL_DATA`
  Gap: current-model data are not current-hardware calibrated with immutable holdout.
- `fig9`: aligned=no, status=`PASS_CAMPAIGN_ANALYSIS`
  Gap: execution-driven request/byte/FIFO ledger validation is incomplete.
- `fig10`: aligned=no, status=`PASS_CURRENT_MODEL_DATA`
  Gap: ten-stage attribution lacks current-hardware total/component calibration and holdout.

## Next Actions

- finish all 9 AU/SU/WK campaign pairs for calibrated Fig.9.
- replace Fig.8 archived update-throughput CSVs with current setup-inclusive update-only evidence.
- replace Fig.10 archived RQ3 traces with calibrated current-model component ledgers.
- complete correctness-gated current-hardware total-cycle calibration and immutable holdout.
- complete observable component-cycle calibration without summing overlapping event intervals.
- close request, byte, and finite-FIFO ledgers for both architectures.
