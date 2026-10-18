# Paired Resident Board Replay

## Scope

This offline check owns the transition from six complete FPGA matrix reports
to 24 paired wall-time ratios. It does not program a card, modify the live
runner, rerun an oracle, attest systemd termination, or admit a final figure.
Incomplete matrices fail; missing rows are not projections.

Each arm has SSSP, reciprocal CC and residual PR on AU, SU, WK, SO, PK, LJ,
LJ08 and R19, with at least three independently restored repetitions. The
timing boundary is `resident_update_to_final_readback_wall_including_host_relaunch`:
old state and the batch are already resident; actual update, propagation,
inter-round work and final readback are inside the continuous wall timer.
CPU graph preparation, programming, initial preload and final oracle are not.

## Checks And Ownership

The owner is `fullgraph_readiness/paired_board/`:

- `analysis.py` replays raw output and resource records, checks execution
  contracts and aggregates complete matrices. `study.py` revalidates original
  offline/artifact admissions and the source/input/runtime pin closures.
- Each raw stdout/stderr is reparsed by its own arm's analyzer. A stored PASS,
  changed timing field, failed/partial child, different command, missing smoke,
  memory-limit/OOM event or pin drift prevents acceptance.
- Graph hashes, dimensions, sources and physical batches must match. SSSP and
  ResPR have eight edits; reciprocal CC has sixteen. All algorithms retain
  their frozen final-oracle and convergence rules.
- Both arms use admitted 150-MHz artifacts, the same two-CPU affinity,
  repetition count, driver/runtime library identities and U55C shell. Different
  card BDFs/serials are permitted; they remain in the individual reports.
- Every individual wall time is retained. The exported speedup is
  `median(G+R wall_ms) / median(Spine wall_ms)`, not an average of pairwise
  ratios. Three repetitions are restored processes, not three chained batches.

The success status is
`PAIRED_RESIDENT_BOARD_REPORTS_REPLAYED_NOT_BASELINE_OR_FIGURE_ADMISSION`.
Original-G/R controls, integrated path performance, simulator alignment,
stage calibration and final figure packaging remain separate gates. In
particular, matching a complete wall time does not calibrate Fig10's stages.
Spine's per-round full-state readback and counted host PR correction remain
disclosed implementation costs, not an all-device claim.

## Reproduction

Provide a JSON list in SSSP, CC, ResPR order. Each item has exactly
`algorithm`, `gr` and `spine`; each arm contains absolute `report` and
`admission` paths. The G+R admission is that algorithm's routed-admission JSON;
the Spine admission is the fixed-host/artifact freeze JSON. For example, the
SSSP item is:

```json
{
  "algorithm": "weighted_sssp",
  "gr": {"report": "/campaign/gr-sssp/results.json", "admission": "/campaign/gr-sssp-admission/summary.json"},
  "spine": {"report": "/campaign/spine-sssp/results.json", "admission": "/campaign/spine-freeze/results.json"}
}
```

Add the analogous `connected_components` and `residual_pagerank` items. From
the simulator worktree, use a fresh output directory:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.paired_board \
  --preflight /campaign/fullgraph-host-readiness-v3 \
  --requests /campaign/paired-requests.json \
  --output /campaign/fresh-paired-replay
```

This hashes the live indexed inputs/artifacts, so the original files must
still exist and be unchanged. Run in a bounded offline scope with the system
reserve respected while builds continue. Outputs are `results.json` (all
repetitions, input/report/raw pins and non-claims) and `paired_wall.csv`
(24 medians and ratios). Failures retain a diagnostic report, without a CSV.
An existing destination is never overwritten.

Synthetic tests cover all six matrices, raw/report disagreement, reordered or
missing cases, changed commands/inputs/runtime/clock, promoted claims, OOM,
pin drift and the median calculation. They are not hardware measurements.
No live paired result is claimed by this implementation checkpoint.
