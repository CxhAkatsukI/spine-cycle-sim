# Candidate10 opt-v2 versus K=1 formal matrix

This directory stores the committed summary layer for the exact-idle formal
matrix completed on 2026-07-28. The raw per-controller DRAMSim3 directories
remain under `/data/tmp/chuxiao/candidate10_opt_v2_k1_formal_matrix_exact_idle_20260728`.

- `comparison_manifest.json`: run completion, commands, fingerprints, and HBM contract
- `results.csv`: 146 validated system rows
- `pairs.csv`: 73 correctness-gated architecture pairs
- `analysis/`: fail-closed grouped, bottleneck, update, and provenance summaries

The overall 2.117x geometric mean is synthetic-heavy. For paper claims, report
the real compact subset and algorithm-specific rows from `analysis/pair_details.csv`.
