# Candidate10 routed hierarchy component power

All four builds pass source-hash, hierarchy-closure, and frozen-value checks.
The CSV groups direct ULP children without double counting nested hierarchy
rows. Values are Vivado vectorless estimates with `Low` confidence: they
support component attribution and implementation feasibility, not workload
energy or board-power claims.

```bash
python3 scripts/analyze_vivado_component_power.py \
  --out-dir /tmp/candidate10-component-power \
  --paper-data-dir /tmp/candidate10-paper-data
```
