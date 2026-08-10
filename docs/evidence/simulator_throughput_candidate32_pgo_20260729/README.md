# Exact PGO build evidence

This directory contains compact evidence for simulator throughput milestone
12. The full commands, raw paths, limitations, and interpretation are in
`docs/simulator_throughput_candidate32_pgo_20260729.md`.

- `equivalence_manifest.json` and `equivalence_rows.csv` record the
  fail-closed comparison against Candidate 24.
- `candidate_results.csv` and `candidate_pairs.csv` preserve the controlled
  correctness, cycle, wall-time, traffic, and energy rows.
- `build_manifest.json` records the compiler, profile, plugin, DRAMSim3, and
  HBM configuration provenance.

The profile contains observations from both Spine and normalized
GraSU+ReGraph. PGO changes host execution only; every compared simulator
observable is exact.
