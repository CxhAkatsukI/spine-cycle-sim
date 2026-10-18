# Full-Graph Host Readiness

## Scope

This is an offline prerequisite for the later FPGA matrix, not a hardware
measurement or a GraSU/ReGraph publication-performance comparison. It compiles
the unchanged current production host for SSSP, CC and residual PageRank and
uses its existing `--prepare-only` branch. That branch returns before device
selection, OpenCL context creation or FPGA programming. No bitstream is passed
to these commands. Neither a timing model nor production HLS is modified.

The frozen matrix is the complete 24-input insertion/u8 manifest at
`/data/tmp/chuxiao/fullgraph_fpga_workloads_20260806/manifest.json`:

- AU, SU, WK, SO, PK, LJ, LJ08 and R19, without an externally compacted
  topology or vertex-ID input. The production host still performs its internal
  vertex mapping; this check makes no physical-ID locality claim.
- SSSP and ResPR have eight physical edits; reciprocal CC has sixteen.
- Hosts retain their declared old-graph/reference convergence policies.
  Preparing a CPU reference is not proof of FPGA convergence or correctness.
- FullPR, deletions/fallback, larger batches, continuous multi-batch hardware
  and original-paper reproductions are outside this preparation check.

## Execution And Acceptance

The owner is
`spine_cycle_sim/experiments/evaluation_impact/fullgraph_readiness/`:
`preparation.py` owns identities, the fixed matrix and compilation commands;
`study.py` owns bounded execution; `diagnostics.py` reviews structured compiler
output; `analysis.py` accepts only the offline output contract. `recheck.py`
replays terminal acceptance from raw logs; `delivery.py` owns the bounded
portable capsule. The execution CLI is `python3 -m` on that package.

The host build preserves full `GRASU_MAX_CACHE_SEGMENT=131072` capacity and
enables `GRASU_REGRAPH_HOST_ROW_LINE_READ=1` for the optimized adapter layout.
It records the compiler version, flags, affinity, frozen sources, dependency
headers, binaries, Python interpreter and imported experiment runners. A clean
production worktree is required. Initial, post-admission and final SHA-256
checks cover all inputs. Small files are also hashed between steps; large-file
path/inode/size/mtime/ctime checks avoid repeatedly reading the full graph
matrix during memory polls. A final hash failure rejects the whole study.

Three six-partition correctness smokes precede the large matrix. Any smoke
failure stops full-graph execution. A large-case failure remains in the report
and the remaining predeclared rows are attempted. Each child has separate raw
stdout/stderr, command, timeout and resource records. Acceptance requires:

1. All 24 distinct graph/algorithm pairs attempted and passed, not 24 copies
   of one passing row; all three smokes passed first.
2. Exact input dimensions, physical-update conservation, converged CPU oracle,
   local-dst19 destination sharding, four frontends/shared downstream and a
   consistent PMA slot ledger.
3. The production runtime planner succeeds at full capacity. SSSP/CC also
   explicitly print and check 23 graph channels, at most 512 MiB per channel,
   and resident old-converged state. ResPR's prepare line does not print those
   channel maxima; its frozen planner checks capacity internally. No additional
   direct measurement is inferred from missing fields.
4. No unreviewed compiler diagnostics, runtime diagnostics, board-execution
   output, pin drift or safely stopped child.

Compilation retains `-Wall -Wextra -Werror` and requests GCC JSON diagnostics.
An empty array is accepted, as is one exact `note` from `CL/cl2.hpp` saying the
header has been renamed to `opencl.hpp`. That reviewed upstream header message
is retained in raw stderr and `compiler_diagnostics`, not suppressed. Any other
note, warning, error, nested diagnostic, duplicate, malformed JSON or stdout
fails before smokes or graph preparation. The unchanged production source and
its dependency headers remain hash-pinned; no source rewrite is used to remove
the message.

The only successful decision is
`FULLGRAPH_HOST_PREPARATION_PASS_NOT_BOARD_OR_PERFORMANCE`.
`board_programmed`, `hardware_timing_measured`, `publication_match` and
`production_baseline_admitted` remain false. Correct physical new-G metadata
binding, G-to-R handoff, routed timing and measured convergence still require
the actual hardware gates.

## Memory And Reproduction

Use a fresh output directory and an exact 24-GiB hard cgroup, finite high limit,
zero swap and group OOM kill. The atomic shared lease reserves this entire
budget, every other bounded build's complete budget, and a 32-GiB system
reserve. Unknown/unbounded peers prevent admission. Other FPGA tools need not
exit: two 40-GiB peers give a 136-GiB admission threshold, while one gives
96 GiB. Waiting is bounded to 18 hours by default and holds no reservation.
After admission a live-memory/process-tree watchdog guards every child.

Three host compilations run sequentially (300 seconds each), followed by
sequential smokes and full-graph preparations (1,800 seconds each). No graph
parallelism is assumed safe. OOM, timeout and watchdog stops are failures,
not projections or capacity passes. The whole service also has a bounded
lifetime. A unit termination must be read alongside the last saved report;
`RUNNING` is never a completed result.

Example, from the simulator worktree:

```bash
systemd-run --user --unit=spine-fullgraph-readiness-20261016-v1 \
  -p MemoryMax=24G -p MemoryHigh=22G -p MemorySwapMax=0 \
  -p OOMPolicy=kill -p CPUQuota=200% -p RuntimeMaxSec=151200 \
  -p TasksMax=256 -p KillMode=control-group -p TimeoutStopSec=30 \
  --working-directory="$PWD" \
  /usr/bin/taskset -c 116,117 /usr/bin/python3 -m \
  spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness \
  --integration /home/chuxiao/grasu-regraph-integration \
  --manifest /data/tmp/chuxiao/fullgraph_fpga_workloads_20260806/manifest.json \
  --xrt /opt/xilinx/xrt --hls /data/yxx/tools/xilinx/Vitis_HLS/2024.1 \
  --output /data/chuxiao/experiments/baseline_hardware_validation_20261015/fullgraph-host-readiness-v1
```

Read `results.json`, `raw/*.stdout.txt`, `raw/*.stderr.txt` and
`raw/*.resources.json` under the
attempt directory, plus the systemd terminal result. Keep an unsuccessful
attempt intact and choose a fresh output path for a retry.

## Checkpoint

Thirty focused unit tests cover execution, analysis and portable delivery,
including immediate admission with another FPGA tool running, memory-wait
timeout, drift, smoke failure, full-case failure retention, exact matrix
coverage, strict compiler diagnostics and inconsistent archived evidence.
Mocked runner tests do not compile hosts, operate FPGA hardware or validate
large graphs. Fifteen repository-organization tests also pass.

The first live attempt, `fullgraph-host-readiness-v1`, was admitted and stopped
at its compiler-output gate at 2026-10-16 02:39 UTC. Compilation exited
successfully; the only stderr was the upstream `CL/cl2.hpp` rename note. No
smokes or full-graph cases ran. Its failed report and raw output are preserved.
The real failure capsule in `fullgraph-delivery-preflight-v1` under the campaign
root passes portable verification, without promoting the attempt to success.

The fresh `fullgraph-host-readiness-v2` uses structured diagnostic review and
otherwise keeps the same production revision, matrix, memory policy, compiler
optimization and offline-only boundary. It freezes simulator revision
`907ac6de705171d7aa758a3d9ee8996920e04c7f` and production revision
`6f5ebf2b0679f04f4f6e035e850fce7b6043a660`. Its service is
`spine-fullgraph-readiness-20261016-v2.service`, invocation
`ab16c4f930eb4b649ec7f58e7dea18f1`.

At 2026-10-16 03:42:23 UTC, v2 completed with
`FULLGRAPH_HOST_PREPARATION_PASS_NOT_BOARD_OR_PERFORMANCE` and service exit
code zero. All three six-partition smokes and all 24 full-graph preparations
passed. The 30 child steps comprise three compilations, three smokes and the
24 graph preparations. No compiler/runtime errors, pin drift, memory-limit
events or OOM events were recorded.

| Dataset | Vertices | Destination partitions | SSSP initial edges | Algorithms passed |
| --- | ---: | ---: | ---: | --- |
| AU | 515,281 | 8 | 390,847 | SSSP, CC, ResPR |
| SU | 567,316 | 9 | 616,118 | SSSP, CC, ResPR |
| WK | 1,140,149 | 18 | 1,142,352 | SSSP, CC, ResPR |
| SO | 6,024,271 | 92 | 23,724,166 | SSSP, CC, ResPR |
| PK | 1,632,803 | 25 | 44,603,928 | SSSP, CC, ResPR |
| LJ | 4,847,571 | 74 | 85,702,474 | SSSP, CC, ResPR |
| LJ08 | 5,363,260 | 82 | 99,028,542 | SSSP, CC, ResPR |
| R19 | 524,288 | 8 | 15,483,485 | SSSP, CC, ResPR |

Algorithm-specific edge counts are retained in each raw report; the SSSP
column is not an assertion that CC/ResPR use identical edges. The maximum
printed SSSP/CC graph-channel allocation is 327,008,256 bytes (311.86 MiB),
below the 512-MiB per-channel limit. ResPR's planner passed, but its missing
printed channel maxima remain missing. The maximum sampled child-tree RSS
is 18.45 GiB under the 24-GiB hard/22-GiB high limit; systemd separately
recorded a 19.3-GiB service memory peak. These scopes are not interchangeable.

This closes the declared offline CPU-oracle/layout prerequisite only.
Actual new-G metadata binding, integrated RTL/backpressure, multi-shard board
handoff, hardware convergence/timing and the Spine comparison remain open.
The passing preparations do not authorize the guarded compact board hosts
to run the full eight-graph matrix unchanged.

## Portable Evidence

Only terminal reports can be packaged. Keep v1's compiler-output gate failure
and the complete v2 outcome together; a successful compiler exit in v1 does
not retroactively admit that attempt. The capsule contains each report,
all raw logs/resource records, copied production sources, frozen Python
runners, smoke graphs and dependency lists. Large graph inputs, compiled hosts
and toolchain/system dependencies remain SHA-256-indexed in the original
reports rather than copied into Git.

The [delivered evidence index](evidence/index.json) and
[raw capsule](evidence/raw_fullgraph_readiness.tar.gz) preserve both terminal
attempts. The first remains `FAILED_RETAINED` with zero smokes/cases; the
second contains all three passing smokes and all 24 passing cases. Recheck
the committed capsule from the simulator worktree:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.delivery verify \
  --destination docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/fullgraph_readiness/evidence
```

```bash
campaign=/data/chuxiao/experiments/baseline_hardware_validation_20261015
python3 -m spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.delivery build \
  --attempt "$campaign/fullgraph-host-readiness-v1" \
  --attempt "$campaign/fullgraph-host-readiness-v2" \
  --destination /path/to/fresh-fullgraph-evidence

python3 -m spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.delivery verify \
  --destination /path/to/fresh-fullgraph-evidence
```

The verifier reads the archive directly without extracting it or accessing the
original machine-local paths. It checks membership, hashes, frozen snapshots,
terminal status, complete ordered matrix, child resource records, full-cache
compiler commands, reviewed compiler diagnostics and exact prepare-only
commands. Every saved passing case is analyzed again from raw stdout/stderr.
The index cannot promote CPU preparation into hardware timing or baseline
admission. This replays **acceptance of recorded outputs**; it does not rerun
the CPU oracle, reconstruct omitted graph inputs or validate FPGA execution.

Packaging uses a fresh destination, rejects symlinks and file drift, and
bounds the capsule to 64 MiB. Run it in a bounded no-swap scope while FPGA
builds continue; there is no reason to wait for those tools to exit if the
small packaging budget and reserve fit. The focused delivery tests cover
portable verification after removing the live attempt path, retained compiler
failure, missing rows, changed commands/capacity, resource-log disagreement,
rehashed inconsistent outputs, source drift and false board claims.

## Board Continuation

The [fixed-Spine board protocol](spine_resident/README.md) uses the same bounded
executor with an explicit host contract. It does not reuse G+R output parsing
or claim a paired result before both matrices pass.

The [paired-board replay](paired_board/README.md) separately revalidates the
six complete reports, raw logs and pin closures before exporting 24 median
wall-time ratios. It refuses incomplete matrices and does not admit original
baseline performance, stage calibration or final figures by itself.

The offline capsule above remains frozen. The separate board owner comprises
`board_preparation.py` (offline/artifact identity and exact eight-graph plan),
`board_analysis.py` (oracle, convergence and event-ledger checks),
`board_study.py` (exclusive card lease and bounded execution), and
`continuation.py` (exact-prerequisite service orchestration). Tests use synthetic
outputs; passing them does not mean a board matrix ran.

The new production host revision `1a5650c` checks `GRASU_REGRAPH_EXPECT_BDF`
against the selected XRT device before context creation. SSSP, CC and ResPR
each reject an intentionally wrong address with the exact lease diagnostic,
without programming. Those three checks are retained in
`fullgraph-host-bdf-negative-v2` under the campaign root. The earlier v1 omitted
`XILINX_XRT` and failed to enumerate a card; it is a failed harness, not a
successful address check. Offline `fullgraph-host-readiness-v3` rechecks this
host on the original complete matrix; its exact service is
`spine-fullgraph-readiness-20261018-v3.service`, invocation
`762fef3ec2d74791894fa23f1c7ad3ec`. It completed all three smokes and
24 preparations successfully, with zero memory-limit/OOM events and no errors.
Its terminal report SHA-256 is
`89e0e5a226f3b56c5f64001ec760e23b66ffebb8ddd3c97e872d5d2d2a69a733`.

Board admission requires the complete successful offline report, frozen host
and source closure, strict algorithm-specific routed timing/topology admission,
unchanged runtime/driver, healthy calibrated U55C and an idle exclusive board
lease. SSSP additionally waits for its separate production G/metadata/continuous
handoff qualifier. The supervisor accepts only the named service invocations
and their hash-bound reports. A changed or failed prerequisite stops it without
programming; completion of an unrelated/restarted unit cannot substitute.

The first board continuation (`fullgraph-board-continuation-v1`) stopped before
requesting a board: systemd collected the successful transient offline unit,
so its invocation identity could no longer be queried. That failure is retained;
it is not a host, capacity, or FPGA correctness failure. A fresh continuation can
use `--completed-preflight-sha256` with the exact terminal digest above. This
explicit path replays all compile, smoke and 24-case raw evidence, verifies the
source/binary/input pins, and records
`PINNED_COMPLETE_REPORT_REPLAY_NOT_SERVICE_EXIT_ATTESTATION`. It does not infer
success from an absent service. A live restarted/failed service still rejects
the request, and algorithm-specific routed admission is unchanged.

The running remote routes and local return followers are kept referenced by
`spine-evidence-retain-routes-20261018-v1.service` on the builder and
`spine-evidence-retain-followers-20261018-v1.service` locally. These small
oneshot retention units do not rerun, modify, or admit builds; they retain the
named services so their exact terminal invocation remains inspectable. Their
dependencies must not be restarted after completion.

Each algorithm first runs the same six-partition smoke, then three complete
repetitions of all eight graphs (25 child attempts). Each process restores the
same initial state and applies one batch; this is not three batches chained
together. The child must pass the complete existing integer/PR oracle, reach
hardware and reference convergence, preserve PMA scan conservation, and pass
the recorded device-event dependency/overlap checks. A child failure stops the
remaining matrix without automatic board resets. FullPR's fixed-round protocol
is deliberately outside this convergence runner.

Run `python3 -m spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.continuation`
in a fixed runner under its own 24-GiB max/22-GiB high/no-swap service with
two-CPU affinity. Its CLI takes `--preflight`, `--output`, `--requests`,
`--preflight-unit` and `--preflight-invocation`. The requests JSON has exactly
three objects with `algorithm`, `unit`, `invocation`, `returned`, `admission`
and `device`; paths are absolute, and admission must lie within the named
follower attempt. `returned` here is the local follower's root, not its binary
subdirectory. Memory leases reserve the full 24 GiB, bounded peers and 32 GiB
system reserve; each board child retains a live watchdog and finite timeout.

### Deployed Continuation

The [exact three-algorithm requests](board_requests.json) are copied to
`fullgraph-board-requests-v1.json` under the campaign root. The supervisor is
`spine-fullgraph-board-continuation-20261018-v1.service`, invocation
`22394ee901054d72a57511bf94e6d1a2`, output
`fullgraph-board-continuation-v1`. It enforces 24-GiB max, 22-GiB high, no swap,
two CPUs (118--119), and a finite 172800-second service lifetime. Its first
observed state is `WAITING_FOR_OFFLINE_PREPARATION`, with no board requested.
This is a deployed waiting workflow, not a successful matrix.

The fixed runner is simulator `237b519`, directory
`production-return-board-runner-237b519` on both hosts. The archive
`production-return-board-runner-237b519.tar.gz` has SHA-256
`2c06795458901aa036cf3e11b23cc13ecebfd6a6aa0914df2f74da2b77b6263c`.
Do not edit that runner or substitute another service invocation. The SSSP
request deliberately names the older independent production qualifier, not
the CC/PR return-only follower. The supervisor serializes the three matrices;
the two board indices in the requests do not authorize concurrent use of the
same card by another process. A failed prerequisite or child remains a failure
and stops the continuation without a reset.

### Current Continuation

The deployed-v1 record above is historical. V2 used the pinned completed
preflight replay and was deliberately stopped while waiting for admitted
artifacts, with no board requested and no matrices run. It was replaced to
share the bounded card/measurement lease with the new fixed-Spine protocol;
it is not a completed board result.

The current supervisor is
`spine-fullgraph-board-continuation-20261018-v3.service`, invocation
`54490a9990f84a6a9414bad3de1caf9c`, output
`fullgraph-board-continuation-v3` under the campaign root. It uses the same
three requests and completed-v3 preflight digest, frozen runner `8e44bf8`,
directory `fullgraph-board-runner-8e44bf8`, and archive SHA-256
`8413f1547e8b0a082948f401d42dd42ecfd291c0b780417489f262d072c1efd2`.
At this checkpoint it is `WAITING_FOR_ADMITTED_ARTIFACTS`, without errors or
completed board matrices. It keeps the same 24/22-GiB limits, zero swap,
two-CPU affinity and bounded service lifetime. The independent four remote
routes continue; neither this waiting state nor the Spine preparation closes
the hardware or original-performance gates.

### Timing Boundary

The host's legacy `setup_inclusive_ms` field begins **after** initial graph,
update, directory and old-state preload. It ends after convergence and final
readback. The board report therefore names it
`resident_update_to_final_readback_wall_including_host_relaunch`: it includes
host relaunch and final readback, but excludes CPU graph/layout preparation,
CPU old-state reference, programming, initial preload and result serialization.
It must not be called full CPU-setup-inclusive latency.

The host's event helper records earliest event start to latest event end,
not a union of individual durations. Those event spans may contain host/transfer
gaps; overlapping kernels are not added together as exclusive stages. Both
wall and span are retained, with the raw event ledger, but neither establishes
ten-stage hardware calibration. A later Spine comparison must match this
window explicitly before producing speedups.

Terminal board decisions are
`FULLGRAPH_ALGORITHM_BOARD_CONVERGENCE_PASS_NOT_SPINE_OR_PUBLICATION_MATCH`
per algorithm and
`THREE_ALGORITHM_FULLGRAPH_BOARD_PASS_NOT_SPINE_OR_PUBLICATION_MATCH`
for the supervisor. They close only the declared new-G+R arm. Original-G/R
publication performance, the corresponding fixed-Spine measurements, modeled
HBM energy and final Figures 7--11 remain independent unfinished work.
