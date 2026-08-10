# GraSU+ReGraph routed Vivado hierarchy-power evidence

The three subdirectories archive the complete implementation log and parsed
hierarchy for the routed weighted SSSP, Full PageRank, and thresholded
residual PageRank whole-system builds. Each report has `Low` activity
confidence and no SAIF/VCD input. It is suitable for implementation-level
component attribution, not workload energy or board-power claims.

Reproduce one parsed ledger:

```bash
python3 scripts/collect_vivado_power_evidence.py \
  --generic-components \
  --label 'GraSU+ReGraph weighted SSSP' \
  --log docs/evidence/candidate10_grasu_regraph_vivado_power_20260728/weighted_sssp/impl_1_runme.log \
  --out-dir /tmp/grasu-weighted-power
```

The fail-closed cross-build aggregation is in
`docs/evidence/candidate10_vivado_component_power_v1_20260728`.
