# Exact AXI backend-wakeup evidence

This directory contains compact evidence for simulator throughput milestone
13. See `docs/simulator_throughput_candidate33_axi_backend_wakeup_20260729.md`
for the mechanism, limitations, raw paths, and interpretation.

- `equivalence_manifest.json` and `equivalence_rows.csv` are the fail-closed
  comparison against Candidate 24.
- `candidate_results.csv` and `candidate_pairs.csv` preserve the controlled
  correctness, timing, traffic, and energy rows.
- `build_manifest.json` records source and binary provenance.

The optimization changes host scheduling only. Architectural cycles and every
published simulator observable remain exact.
