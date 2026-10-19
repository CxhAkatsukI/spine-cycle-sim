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
  memory-throttling/limit/OOM event or pin drift prevents acceptance.
- Graph hashes, dimensions, sources and physical batches must match. SSSP and
  ResPR have eight edits; reciprocal CC has sixteen. All algorithms retain
  their frozen final-oracle and convergence rules.
- Both arms use admitted 150-MHz artifacts, the same two-CPU affinity,
  repetition count, driver/runtime library identities and U55C shell. Different
  card BDFs/serials are permitted; they remain in the individual reports.
- Every individual wall time is retained. The exported speedup is
  `median(G+R wall_ms) / median(Spine wall_ms)`, not an average of pairwise
  ratios. Three repetitions are restored processes, not three chained batches.
- Resident host containment is the recorded 24/22- or 40/36-GiB hard/soft
  budget, with zero swap and a 32-GiB system reserve. Replay checks the exact
  declared cap against cgroup and child records and requires zero `high`,
  `max` and OOM events. Inactive host safety caps may differ between arms;
  throttled timing is never accepted.

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

An active running service with `Result=success` is still waiting. A retained
`active/exited` service is terminal only with the exact invocation, successful
exit and zero main PID. A failed, restarted
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

## Superseded V4 Deployment

Earlier v1--v3 paired followers were stopped before replay while their
producers were waiting; no paired CSV or hardware result was discarded.
The v4 replacement used immutable runner `da7e791` in
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/board-return-runner-da7e791`:

| Item | Identity |
| --- | --- |
| Paired service | `spine-paired-board-continuation-20261018-v4.service` |
| Invocation | `f1b5834d3ff345489e02f9755397c00e` |
| Producer | `spine-fullgraph-board-continuation-20261018-v7.service` |
| Producer invocation | `02306d8928934d2dbd1b584c60dee901` |
| Output | `/data/chuxiao/experiments/baseline_hardware_validation_20261015/paired-board-continuation-v4` |
| Request file | `/data/chuxiao/experiments/baseline_hardware_validation_20261015/paired-board-requests-v4.json` |
| Requests SHA256 | `2a958dc1402eacd2da9d92f08bd01ba8354ac86a663b5c7804871ea989bdae95` |

The producer paths, returned CC artifact and qualification admission change. The
completed fixed-Spine reports and artifact freeze remain unchanged. The
service retains 4/3-GiB containment, zero swap, group OOM kill and a finite
wait, with `RemainAfterExit=yes` for terminal inspection. At redeployment it
was `WAITING_FOR_COMPLETE_BOARD_PRODUCER`, without errors. No speedup or
final-figure admission follows from that state.

## Superseded V5 Deployment

The v4 follower's producer was superseded before replay. Its record remains
unchanged. The superseded v5 follower used the immutable `b0aa357`
runner, whose paired continuation source is unchanged, and the
[registered comparison requests](../../complete_pipeline/production_routing/comparison_candidate/paired_requests.json).
The current admissions are checked against the candidate's fullgraph request
file by `RegisteredPairedRequestTests`; no historical admission is substituted.

| Item | Identity |
| --- | --- |
| Paired service | `spine-paired-board-continuation-20261019-v5.service` |
| Invocation | `2be58f2af7ba4f15b581e98e8b66d1d4` |
| Producer | `spine-fullgraph-board-continuation-20261018-v9.service` |
| Producer invocation | `e612a14bee3b4681ab4a17b795f6c7b0` |
| Output under LROOT | `paired-board-continuation-v5` |
| Runner under LROOT | `current-board-runner-b0aa357` |
| Runner archive SHA256 | `087cad9ececb3ce1359fbed3e5c59439ce70c3af16e16c11531a07230ac38a1f` |
| Request file under LROOT | `paired-board-requests-v5.json` |
| Requests SHA256 | `3d92b64450a4a55cebc9542bbf0e6bcf90ec84b643be91d35dc8d285621d36a2` |

LROOT is `/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.
The offline-only service uses a 4-GiB hard limit, 3-GiB high watermark, zero
swap, group OOM kill, CPUs 118--119, a 172800-second wait and retained terminal
identity. It never operates an FPGA. It waits for all three algorithm reports
and rejects producer failure, changed sources or incomplete matrices. Starting
this follower is not a speedup, simulator calibration or final-figure result.

## Current Candidate Deployment

The current producer is fullgraph v13 and the offline-only follower is paired
v9, using the immutable `resident-board-memory-runner-v1`. Earlier v12/v8
records are retained: v12 was interrupted because LJ host preparation hit its
memory soft limit, not because of FPGA correctness. The current runner rejects
soft-limit events as well as OOM. Exact invocations, runner hash, requests and
the still-pending status are maintained in the
[current comparison candidate](../../complete_pipeline/production_routing/comparison_candidate/README.md#board-host-memory-and-timing-admission).
