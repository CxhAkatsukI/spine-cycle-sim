# Continuous G To SSSP Handoff

## Decision

**Host functional preflight passes; FPGA execution has not run.** This study
adds a bounded single-partition SSSP host to the resident-G test. Nine compact
AU/SU/WK inputs produce 27 checked batch rows. Every final distance and
synchronous active-count trajectory agrees with an independent Dijkstra
oracle. None of these rows is a measured FPGA cycle, publication match,
integrated RTL pass or complete-baseline admission.

The [host evidence index](host_evidence/index.json) contains frozen source,
inputs, contracts, raw output, compiler/header identities and resource logs.
It preserves v1 (18 passing rows), v2 (parser rejection), and v3 (27 passing
rows). The [board-host evidence index](board_host_evidence/index.json) freezes
v4: the same 27 non-timing results, with the actual device BDF and HBM
allocation reported by the compiled board path. No attempt was overwritten. The separate
[G regression index](g_regression_evidence/index.json) records a fresh run of
the original G-only host: all eighteen non-timing state results equal the
earlier guarded-host capsule.

## Matrix And Limits

| Inputs | Batches per input | Policy and useful coverage |
| --- | --- | --- |
| AU/SU/WK mixed-512 | Empty, 256 physical records, remaining 256 | Nonempty batches require deletion fallback |
| AU/SU/WK weight-change-4096 | Empty, 4096 physical records, remaining 4096 | Net weight increases trigger fallback |
| AU/SU/WK warm-decrease-64 | Empty, 64 physical records, remaining 64 | 64 distinct logical decreases overall; AU/SU actually propagate without resetting old distances |

Warm controls select the first 64 distinct decreases whose deletion weight
matches the initial graph, in the frozen weight-change input's pair order.
They are explicitly derived functional controls, not additional original
traces or cherry-picked timing measurements. Each nonempty batch changes 32
logical edges. WK's fixed source 0 has little reachability: its warm batches
terminate with zero newly active vertices, so it does not establish meaningful
propagation performance. AU/SU warm batches take 3--8 synchronous rounds.

Each graph has 8192 initial edges, fewer than 65536 vertices and one native
65536-vertex destination partition. Inputs reserve future positive variants;
all physical edits are hot-cache updates. Cold G, native multi-partition
convergence, capacity growth, CC, ResPR and FullPR are outside this preflight.
These compact cases do not replace the requested eight-large-graph matrix.

## Data Path And Timing

The host starts with the old graph's converged source-0 distances, then keeps
PMA and state BOs resident over three consecutive batches. G receives only
that batch's physical updates. The adapter binds the **same** four PMA BOs
and row BO written by G; no CPU compact-edge reconstruction or graph restore
is allowed between G and R. R loops until its device active count reaches
zero, including the final no-change round, with a declared 2048-round limit.
Both source-state replicas and apply state are checked after publication.

For insertion/decrease-only net changes, the host detects changed sources
and writes active bits into the resident distance replicas. A net removal or
weight increase instead resets distances and recomputes on the updated PMA.
This host-side policy is explicit; it is not claimed as device-generated
seeding or the final optimized host implementation.

The intended board E2E window includes net-policy detection, update packing,
G DMA/launch/wait/publication, seed or fallback DMA, all R rounds, convergence
readbacks and final result readback. One-time parsing/reservation/programming
and old-state upload are separate. Independent correctness oracles and full
PMA/metadata/state-replica diagnostic readbacks are outside this window.
The current net-policy implementation copies/scans a host edge map; its cost
is included, not assumed free. Kernel event intervals are unioned rather
than summed across overlapping CUs.

`--model-check` invokes no FPGA API and reports G/R busy time and hardware
E2E time as zero. Its host preparation/oracle costs are not device latency.
The `--board` path only compiles in this preflight. The guarded launcher now
implements strict new-G route admission, the shared board lease, runtime
checks, bounded execution and event analysis. The FPGA matrix has not run.

## Guarded Board Execution

The launcher reuses the isolated-G execution engine through a small explicit
experiment specification. Route, runtime, lease and memory policies have one
owner; this study supplies its own host identity, convergence/event analyzer
and success boundary. It does not copy a second board supervisor.

Admission requires the completed new search/full-cache route, matching
150-MHz clock and connectivity, all 22 expected CUs, and passing final setup,
hold and pulse-width timing. The frozen host must include both the
pre-programming BDF guard and reported BDF. The preflight's three active-count
trajectories are carried into each board case, not inferred from a final
zero alone. Earlier v3 host evidence is still valid as host evidence, but its
binary predates the reported-BDF requirement and cannot enter this launcher.

Raw events must contain ten G kernels/barriers per batch, five R kernels for
each convergence round, all nonempty update-DMA lanes, exactly the required
seed or fallback transfers, one active-count readback per round and the final
result readback. Analysis rejects missing/duplicate events, cross-batch
overlap, a readback before kernel completion, inconsistent event unions and
events exceeding the reported host-inclusive boundary.

`gr-board-unfinished-gate-v1` exercised the real entry point with `--execute`
against the still-running new-G route. It stopped at admission with
`FAILED_RETAINED`, `board_started: false`, no board attempts and no programming.
This is an expected rejection check, not failed FPGA execution or measured
correctness. Its raw report remains in the campaign directory below.

The default three repetitions cover all nine inputs, for 81 batch rows if
every board case passes. A passing run admits only this compact, hot-only,
single-partition correctness/timing window. It does not establish original-G
performance, a publication match, cold/multi-shard behavior, integrated RTL
or the requested full-graph baseline comparison.

The shared [conditional board queue](../continuous_board/execution/README.md#conditional-board-queue)
can wait for the exact new-G route invocation, check final routed timing,
then execute isolated G before this handoff matrix. It waits for that required
artifact, not for other FPGA tools to exit. Both hosts and transitive runner
sources are pinned before waiting; a failed gate stops without resetting a
board or retrying. Queue readiness is not measured hardware correctness.

## Retained Failure And Compatibility

v2 failed before graph construction because the inherited test parser allowed
only 512 or 8192 update records, not the new warm control's 128. No G/R
execution or hardware failure occurred. The fix adds an explicit opt-in
128-record native-partition input scope to the handoff caller. Existing
callers retain their original defaults. UBSan unit checks cover this boundary
and the SSSP seed, fallback, invalid-input and convergence rules.
The v3 rerun preserves all eighteen original handoff non-timing results and
adds nine warm-control rows. The unchanged original G-only scope is rerun
separately, rather than inferred from successful compilation.

v3 host compilation and execution take about eleven seconds overall, with
roughly 395 MiB maximum compiler-process RSS recorded by `wait4`, not a
simultaneous process-tree sum. Each step is bounded by a
4-GiB cgroup, 3-GiB high watermark, no swap, 900-second timeout, CPUs 124--125
and a 104-GiB available-memory reserve. These are verification resource
measurements, not FPGA performance. Other FPGA tools need not exit when the
full concurrent budgets fit.

v4 recompiles the reported-device host with the same flags and scope. Its
binary SHA-256 is
`e92c8250085509110dee6a7cb4291d5d73582598ab9891126095a0f3262faff4`.
All 27 non-timing rows equal v3; compilation takes 6.17 seconds with
402972 KiB maximum compiler-process RSS (`wait4`, not process-tree sum).
The focused regression suite passes 265 tests. Raw command, stdout/stderr and
resource records are in `verification-gr-continuous-board-v1/`: 8.54 seconds,
106596 KiB sampled peak process-tree RSS, 2-GiB hard bound, no swap, CPU 123
and a 104-GiB reserve. Mocked board-runner tests exercise orchestration and
rejection contracts; they are not FPGA measurements.

## Code And Reproduction

Code owners are under
`cpp/tests/evaluation_impact/common_g/continuous_handoff/` and
`spine_cycle_sim/experiments/evaluation_impact/common_g/continuous_handoff/`.

| File | Responsibility |
| --- | --- |
| `resident.hpp`, `resident_test.cpp` | Net-edge seed/fallback semantics, synchronous reference and independent shortest-path oracle |
| `compute.hpp` | Native single-partition R ABI, resident state, direct PMA handoff and convergence loop |
| `control.cpp` | Three-batch orchestration, explicit timing boundaries and raw events/results |
| `preparation.py` | Freeze production preparation, ABI sources, native inputs and declared warm controls |
| `study.py` | Bounded unit/host compilation and complete host-model matrix |
| `analysis.py`, `delivery.py` | Reject incomplete scope or promoted claims; reanalyze and seal raw evidence |
| `execution.py` | Validate the guarded frozen host and reuse shared route/runtime/lease execution |
| `events.py` | Check kernel/DMA conservation, convergence trajectories and measured timing windows |

From the simulator repository root:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_handoff.study --help
python3 -m unittest tests.test_grasu_continuous_handoff tests.test_grasu_continuous_handoff_delivery tests.test_grasu_continuous_handoff_execution
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_handoff.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/continuous_handoff/host_evidence"))'
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_handoff.execution --help
```

Supply a fresh `--output`, the original GraSU kernel `--upstream`, production
HLS `--integration`, and installed `--xrt`. Use an enclosing user systemd
service with 6-GiB hard/5-GiB high/no-swap limits and a bounded lifetime. Raw
attempts are under
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.

For board admission, supply `--preflight` pointing to v4, `--route` to the
completed new-G route, `--original` to the old reference xclbin and `--output`
to a new directory. Without `--execute`, only admission is attempted.
Execution also requires an enclosing user systemd service with 8-GiB hard,
7-GiB high, no swap, group OOM kill and a bounded lifetime. The shared runner
enforces a 600-second per-case limit, CPUs 124--125 and a 104-GiB available
reserve. Board identity/occupancy are checked under the existing shared lease.

Do not invoke `probe --board` manually to bypass admission. The full-new-G
route remains a separate running experiment. The adapter-only link generated
an xclbin but failed final HBM setup timing at -0.032 ns; it is neither an
admitted board image nor a substitute for the new-G route.
