# Exact event-driven ReGraph evidence

This directory contains compact evidence for simulator throughput milestone
14. See `docs/simulator_throughput_candidate39_event_driven_regraph_20260729.md`
for the mechanism, limitations, raw paths, and reproduction commands.

- `equivalence_manifest.json` and `equivalence_rows.csv` are the fail-closed
  comparison against Candidate 24.
- `results.csv`, `pairs.csv`, and `comparison_manifest.json` preserve the
  controlled correctness, timing, traffic, energy, and provenance rows.

This is a simulator host-runtime optimization only. It does not change the
modeled architecture or any accelerator performance result.
