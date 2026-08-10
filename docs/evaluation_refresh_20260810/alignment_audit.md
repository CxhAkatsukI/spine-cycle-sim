# Evaluation Refresh Alignment Audit

Status: `INCOMPLETE`

## Campaign

- Analysis: `/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen/analysis_partial`
- Summary status: `PARTIAL`
- Observed executions: `11/18`
- Complete pairs: `2/9`
- Paired algorithms: `weighted_sssp`
- Paired datasets: `sx_askubuntu, sx_superuser`

## Figures

- `fig7`: aligned=yes, status=`PASS`
- `fig8`: aligned=no, status=`INTERIM_ARCHIVED_SIMULATOR_DATA`
  Gap: still uses archived update-only evidence.
- `fig9`: aligned=no, status=`INTERIM_ARCHIVED_SIMULATOR_DATA`
- `fig10`: aligned=no, status=`INTERIM_ARCHIVED_SIMULATOR_DATA`
  Gap: still uses archived RQ3 component traces.

## Next Actions

- finish all 9 AU/SU/WK campaign pairs for calibrated Fig.9.
- replace Fig.8 archived update-throughput CSVs with calibrated campaign-derived rows.
- replace Fig.10 archived RQ3 traces with calibrated current-model component ledgers.
