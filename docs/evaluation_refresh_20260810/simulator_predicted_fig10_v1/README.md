# Simulator-predicted Figure 10

This packet presents a normalized cycle breakdown from the execution-driven
Spine simulator. It is not an FPGA per-stage measurement or an FPGA-calibrated
breakdown. All eleven bars use simulator plugin `7563b028e61e792e7043a582682dd26d0e3d8cc3e2407021f144519d0ef57bf6`.

## Scope

- `Zero-net / Syn`: synthetic reciprocal update reduced to no effective graph
  change; this uses the paper target's no-repair semantics.
- `Shallow insert / AU, SU, WK`: batch-8 insertion on AskUbuntu, Superuser, and
  WikiTalk traces.
- `Deep carry / L1, L3, L5`: synthetic batch-8 traces forcing carry through
  level 1, 3, or 5.
- `PR correction / FL, SU, WK`: thresholded residual PageRank correction on
  Flickr, Superuser, and WikiTalk.
- `Deletion fallback / Syn`: synthetic weighted-SSSP deletion fallback.

The ten-stage ledger is grouped for readability:

- `Maint.` = transfer + reduce + carry + directory;
- `Seed/pub.` = seed + switch/publication;
- `Resolve` = history/edge resolution;
- `App` = algorithm application;
- `Drain` = source/reactivation drain + synchronization.

Each bar is independently normalized by its own simulated end-to-end device
cycle interval. Therefore, the figure explains how the dominant stage changes
across realized-work classes; it does not compare absolute latency between
bars. The source analysis admits only correctness-passing Spine runs. This
packager additionally requires one plugin hash, complete five-class coverage,
closed direct ten-stage and aggregate ledgers, and exact cycle conservation.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/package_simulator_predicted_fig10.py
```

Outputs:

- `fig10_simulator_predicted_breakdown.pdf` and `.png`;
- `normalized_breakdown_rows.csv`;
- `manifest.json` with source and output hashes.
