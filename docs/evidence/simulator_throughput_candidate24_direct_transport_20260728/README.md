# Exact direct DRAMSim3 transport evidence

This directory contains the compact, reviewable evidence for simulator
throughput milestone 11. The raw SST and DRAMSim3 directories are retained
under `/data/tmp/chuxiao/` and are listed in
`docs/simulator_throughput_candidate24_direct_transport_20260728.md`.

- `equivalence_manifest.json` and `equivalence_rows.csv` are the fail-closed
  frozen-pair verdict. Every architectural result field and all 26 DRAM JSON
  files match; only the explicit backend provenance changes.
- `candidate_results.csv` and `candidate_pairs.csv` preserve the controlled
  cycle, wall-time, correctness, traffic, and energy rows.
- `micro_standard.json` and `micro_direct.json` cover sequential reads,
  cross-row reads, and mixed reads/writes.
- `payload_standard.json` and `payload_direct.json` validate write payload
  commit and read payload return behavior.

The direct transport is an optional host-runtime implementation of the same
timing contract. It is not an analytical HBM approximation and does not alter
either accelerator architecture.
