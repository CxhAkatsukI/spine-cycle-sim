# Evaluation Refresh Alignment Audit

Status: `INCOMPLETE`

## Campaign

- Analysis: `/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen/analysis_partial_live`
- Summary status: `PARTIAL`
- Observed executions: `15/18`
- Complete pairs: `6/9`
- Paired algorithms: `connected_components, thresholded_residual_pagerank, weighted_sssp`
- Paired datasets: `sx_askubuntu, sx_superuser`

## Figures

- `fig7`: aligned=yes, status=`PASS`
- `fig8`: aligned=no, status=`INTERIM_ARCHIVED_SIMULATOR_DATA`
  Gap: still uses archived update-only evidence.
- `fig9`: aligned=no, status=`PARTIAL_CAMPAIGN_ANALYSIS`
- `fig10`: aligned=yes, status=`PASS_CURRENT_MODEL_DATA`

## Next Actions

- finish all 9 AU/SU/WK campaign pairs for calibrated Fig.9.
- replace Fig.8 archived update-throughput CSVs with current setup-inclusive update-only evidence.
