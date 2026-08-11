# Evaluation Refresh Alignment Audit

Status: `INCOMPLETE`

## Campaign

- Analysis: `/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen/analysis_complete_live`
- Summary status: `PASS`
- Observed executions: `18/18`
- Complete pairs: `9/9`
- Paired algorithms: `connected_components, thresholded_residual_pagerank, weighted_sssp`
- Paired datasets: `sx_askubuntu, sx_superuser, wiki_talk_temporal`

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

- replace Fig.8 archived update-throughput CSVs with current setup-inclusive update-only evidence.
- replace Fig.10 archived RQ3 traces with calibrated current-model component ledgers.
- complete correctness-gated current-hardware total-cycle calibration and immutable holdout.
- complete observable component-cycle calibration without summing overlapping event intervals.
- close request, byte, and finite-FIFO ledgers for both architectures.
