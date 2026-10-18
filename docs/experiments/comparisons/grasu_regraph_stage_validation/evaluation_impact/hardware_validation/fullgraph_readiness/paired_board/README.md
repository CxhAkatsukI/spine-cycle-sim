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

## Unattended Continuation

`paired_board/continuation.py` waits for an explicitly named full-graph
continuation service **and invocation**. It then calls the same offline
replay above, without operating either FPGA. Supply the paired requests
before waiting; the existing Spine reports/admissions, offline preflight,
request file and runner are pinned throughout the wait.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.paired_board.continuation \
  --preflight /campaign/fullgraph-host-readiness-v3 \
  --requests /campaign/paired-requests.json \
  --producer-output /campaign/fullgraph-board-continuation-v4 \
  --producer-unit exact-fullgraph.service \
  --producer-invocation 0123456789abcdef0123456789abcdef \
  --output /campaign/fresh-paired-continuation
```

An active service with `Result=success` is still waiting. A failed, restarted
or collected producer is rejected. Its terminal report must bind the same
offline preflight, exactly three complete algorithm children, their hashes
and the admissions in the paired requests. A terminal systemd success alone
cannot admit a matrix. After replay the producer must still be the same
terminal invocation. The wait is bounded to at most 172800 seconds, and an
existing output is never overwritten. Keep a retention service for the
producer so systemd does not collect its identity before this check.

Outputs are the supervisor's `results.json` plus the unchanged replay package
under `paired_replay/`. Only the producer's service exit is attested here;
the nested report remains an offline replay. Neither success promotes final
figures or original-paper performance matching. Tests cover waiting,
timeouts, changed services, incomplete/foreign children, pin drift and replay
failure; those tests are synthetic, not FPGA results.

## Historical Deployment

The 2026-10-18 deployment uses the frozen `ba441f7` runner in
`/home/chuxiao/spine-cycle-sim/spine-cycle-sim-paired-return-ba441f7`:

| Item | Identity |
| --- | --- |
| Paired service | `spine-paired-board-continuation-20261018-v1.service` |
| Invocation | `27ce62e7d7d140fc952cdc01b2365534` |
| Producer | `spine-fullgraph-board-continuation-20261018-v4.service` |
| Producer invocation | `65221c0d74bb44038e403bd4ae073724` |
| Output | `/data/chuxiao/experiments/baseline_hardware_validation_20261015/paired-board-continuation-v1` |
| Runner archive SHA256 | `be0686b30b9f8ff3c070c3d6b2979be7756b3ab8bb3f323d714921bcdd2fc2be` |
| Paired requests SHA256 | `f64648e9b81156878eb2b1f448d69acb4bf7ee3d277016cd65252ce61ae7732a` |

Its offline-only cgroup has a 4-GiB maximum, 3-GiB high watermark, zero swap
and group OOM kill. At the deployment checkpoint it is
`WAITING_FOR_COMPLETE_BOARD_PRODUCER`: the producer still waits for routed
artifacts. No paired speedups, board programming or final figures are implied
by this waiting service. It must reject a changed producer invocation or an
incomplete matrix instead of analyzing partial rows as a complete result.

## Current Deployment

The v1 paired follower was stopped before replay while its producer was
waiting; no paired CSV or hardware result was discarded. The replacement
uses the immutable `5058f14` runner in
`/home/chuxiao/spine-cycle-sim/spine-cycle-sim-board-memory-5058f14`:

| Item | Identity |
| --- | --- |
| Paired service | `spine-paired-board-continuation-20261018-v2.service` |
| Invocation | `5c24a1fcc4cb42d1a1b6bec4feb066de` |
| Producer | `spine-fullgraph-board-continuation-20261018-v5.service` |
| Producer invocation | `098dd7c6994e4d9c96753f88943a2f6e` |
| Output | `/data/chuxiao/experiments/baseline_hardware_validation_20261015/paired-board-continuation-v2` |
| Request file | `/data/chuxiao/experiments/baseline_hardware_validation_20261015/paired-board-requests-v2.json` |
| Requests SHA256 | `059520398a18d5a228f91e74ae1dcfcd04e1e1374b488e2ca7d0137a52ec41a2` |

Only the new producer paths and SSSP qualification admission change. The
completed fixed-Spine reports and artifact freeze remain unchanged. The
service retains 4/3-GiB containment, zero swap, group OOM kill and a finite
wait, with `RemainAfterExit=yes` for terminal inspection. At redeployment it
was `WAITING_FOR_COMPLETE_BOARD_PRODUCER`, without errors. No speedup or
final-figure admission follows from that state.
