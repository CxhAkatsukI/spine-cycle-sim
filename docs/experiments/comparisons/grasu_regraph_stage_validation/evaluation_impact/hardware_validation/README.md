# Hardware Validation Campaign

## Scope And Acceptance

This campaign resumes the existing baseline-admission study on 2026-10-15.
It does not edit the paper or overwrite earlier evidence. A queued build,
an isolated HLS clock estimate, and a source-level prediction are not a
successful routed baseline or publication-performance reproduction.

| Gate | Required result | Initial status |
| --- | --- | --- |
| G components | Paired original/registered full-cache C simulation, synthesis and RTL; finite-search RTL and 5-ns estimate | Fresh attempts running/queued; no integrated-G admission |
| Complete new G | Search, both cache halves, weighted/local-destination ABI, coherent metadata copies, actual host bindings, complete state checks and resource fit | Not integrated |
| R controls | Original publication configuration A, source A4 and actual adapter/K4 measured separately; disclose ports, credits and memory differences | Prior predictions are not board measurements |
| Physical handoff | G-produced PMA consumed directly by adapter/R; correct resident multi-batch state and measured host costs | Source controls exist; new hardware gate open |
| Routing and board tests | Correct fixed-clock bitstreams, full output checks, matched stage windows and repetitions | Adapter-only route must remain distinct from new-G route |
| Spine comparison | Same graph, old converged state, raw update batch and convergence rule; SSSP/CC/ResPR on all eight declared graphs, failures retained | No replacement speedup claimed |
| Figure delivery | New versioned Figures 7--11 package in this repository, with code, inputs/provenance, previews and explanation | Historical handoff remains frozen |

The approximately 10% source/publication comparison target is an acceptance
test, not permission to fit arbitrary timing factors. Original-publication
reproduction, same-platform source controls and actual integrated performance
have separate decisions. Unsupported original-paper conditions must be
reported rather than silently replaced with a different experiment.

## Execution Order

1. Close the paired cache and isolated finite-search HLS/RTL gates. Do not
   infer integrated timing from a passing component.
2. Finish R credit/window controls and replay the old twelve rows exactly.
   Keep original topology A separate from the four-Little A4 control.
3. Integrate the admitted search/cache candidate into the production G
   repository with reviewable modules. Verify cold and hot paths, metadata
   lifecycle, weighted ABI, complete PMA state and physical G-to-R handoff.
4. Synthesize/export and route only frozen, correctness-checked candidates.
   The already prepared adapter-only SSSP route is a separate R experiment;
   its other ten XOs are unchanged and it cannot admit complete new G.
5. Measure G, adapter/R and host windows on the board. Compare common warm
   states through convergence, not one-hop or cold recomputation on one side.
   Define FullPR's common fixed-sweep/convergence contract before timing it.
6. Run the complete G+R/Spine matrix and simulator checks. Rebuild only figures
   affected by new inputs or model identities; never multiply old results by
   a single speedup. Stage predictions remain predictions without counters.

For the new host-inclusive window, timing starts before per-batch input
preparation and ends after required result processing. Record DMA, launch,
relaunch and readback separately where possible. One-time resident old-state
construction is outside both warm windows. Never reuse the historical
wrapper's label without checking which operations it actually includes.

## Frozen Starting Points

- Simulator: `490ec86d627e7a72e1f17d359bda54a645d917dd`, branch
  `codex/g-finite-search-schedule`.
- Production G+R: `6f5ebf2b0679f04f4f6e035e850fce7b6043a660`, branch
  `codex/sharded-k4-fullgraph-hls`.
- Existing finite-search source controls:
  `/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-search-pipeline-v1/source-controls-v4/`.
- New raw campaign root:
  `/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.

Each attempt owns immutable source hashes and logs. Inspect its report and
exit code, not just the systemd `Result` of a still-running service. Changes
after the starting commit require a new pin/attempt, not edits to old records.

## Initial Attempts And Safety

| Attempt | Service | Limits and status at launch |
| --- | --- | --- |
| `g-cache-full-v1` | `spine-grasu-full-cache-20261015-v1.service` | Two serial arms; tool 6 GiB hard/5 GiB high, 24 GiB reserve, 900 s per arm |
| `g-search-hls-v1` | `spine-grasu-search-pipeline-20261015-v1.service` | Waits for cache service to terminate; tool 8 GiB hard/7 GiB high, 24 GiB reserve, 1800 s tool timeout |

Both supervisors have a separate 512-MiB hard bound, no swap, a two-hour
runtime limit and unique output paths. Tool invocations are affinity-pinned
to CPU 127. Search reserves any active old route's declared memory budget;
no new route is launched during these component checks. Terminal predecessor
state allows the search diagnostic to run, but does not imply cache passed.

Observed launch `MemAvailable` was approximately 147 GiB. This is not a
permanent allocation: every launch must recheck memory. FPGA routing uses
the existing stricter supervisor: 40-GiB hard/36-GiB high process-tree limit,
24-GiB system reserve, eight consecutive safe samples,
two synthesis/implementation jobs and a six-hour link timeout. The initial
queue serialized FPGA tools; the user subsequently requested memory-admitted
concurrency, described below. The initial queue is retained, not rewritten.
Never drop shared caches, change swap, kill other users' jobs or bypass the
guard to force a run. Verify board availability again before programming.

## Monitor And Reproduce

Run from the simulator worktree. These commands read status only:

```bash
systemctl --user show spine-grasu-full-cache-20261015-v1.service \
  spine-grasu-search-pipeline-20261015-v1.service \
  --property=Id,ActiveState,SubState,Result
jq '{status, errors}' /data/chuxiao/experiments/baseline_hardware_validation_20261015/g-cache-full-v1/results.json
jq '{status, error, analysis}' /data/chuxiao/experiments/baseline_hardware_validation_20261015/g-search-hls-v1/results.json
```

Reproduction entry points and the exact declared stimuli are owned by the
[cache guide](../cache_probe/README.md), [finite-search guide](../search_pipeline/README.md),
[R control guide](../r_credits/README.md) and
[adapter-route guide](../../actual_sharded_k4/adapter_optimization/row_line/directory_tile/hardware/README.md).
Use fresh output paths and the same bounded launch policy, not an unguarded
interactive invocation. Compact results and final decisions will be added
here after the attempts terminate; no running job is recorded as a pass.

## Completed Cache Comparison

The fresh paired attempt completed C simulation, synthesis and all six RTL
transactions for both arms. The [portable evidence index](cache_evidence/index.json)
pins source, complete state checks, commands, raw logs and reports. It can be
verified without the machine-local build directories:

```bash
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/cache_evidence"))'
```

| Complete hot half | Clock estimate, ns | LUT | FF | URAM | BRAM |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original | 3.650 | 217980 | 78911 | 256 | 30 |
| Registered candidate | 3.650 | 87684 | 60274 | 256 | 30 |

| Updates / pattern | Original RTL cycles | Candidate RTL cycles |
| --- | ---: | ---: |
| Empty | 278737 | 278743 |
| 16 balanced | 278734 | 278734 |
| 64 balanced | 278782 | 278782 |
| 4096 balanced | 282814 | 282814 |
| 65536 balanced | 344254 | 344254 |
| 4096 single-bank / same-row | 291028 | 291034 |

This supports the registered candidate's functional and isolated estimated
clock feasibility, with essentially unchanged latency and fewer LUTs. It does
not measure HBM on the board, prove routed timing, or admit whole G. Both cache
halves together need 512 URAMs before search, ReGraph and other storage.
Complete preload/writeback remains in every measured RTL transaction.

## Retained Scheduler Failure

`g-search-hls-v1` stopped before invoking HLS. After cache succeeded, systemd
garbage-collected its transient unit; the query returned
`LoadState=not-found, ActiveState=inactive, SubState=dead`. The admission checker
incorrectly rejected this explicit absence as an unknown active-job state.
No search functional or timing failure follows from this attempt. The raw
failure is retained, and any scheduler correction requires a fresh attempt.

`r-credit-v1` hit the same scheduler error after successfully building its
Release executables and passing seven C++ regression tests. It produced no
timing rows. The corrected `g-search-hls-v2` and `r-credit-v2` use fresh output
directories. The R study declares 28 complete-convergence control rows and
must exactly reproduce the prior twelve applicable rows before admission.

## Memory-Admitted Concurrent Routing

The user requested that other FPGA tools need not finish when bounded memory
budgets fit. The queued `r-adapter-route-v1` was stopped before routing;
its `cancellation.json` records the reason and successor. The new attempt is
`r-adapter-route-v2`, with unchanged eleven XOs and hardware configuration.
Only its frozen admission policy differs.

Prepare with `--allow-bounded-builds --background-memory-gib 6`. Admission
requires the route's full 40-GiB hard budget, a 24-GiB system reserve, 6 GiB
for the concurrent R study, and the full finite cgroup budgets of other FPGA
tools. Compiler processes in the same bounded cgroup share one reservation;
an unbounded, swapping or unverifiable compiler is not admitted. The search
scope contributes 8 GiB, so the current threshold is 78 GiB, rather than a
requirement that all other compilers exit. All eight stable samples, hard
containment, live-reserve monitoring and timeouts remain enabled.

The service name `spine-sharded-k4-bank-sssp-20261015-v1.service` is reused for
the fresh invocation so the already-frozen search and R supervisors continue
to reserve its 40-GiB budget. The attempt directory and systemd invocation ID,
not the reused service label, distinguish executions. No prior manifest or
numerical input is changed. This is still an adapter-only route, not new G.

The fresh invocation `0133f725114a4166b873b9054d469bba` reached `ROUTING`
after its eight safe samples. At that instant the isolated search tool had
already exited, so its observed admission threshold was 70 GiB (40 + 24 + 6),
with about 146.7 GiB available. This does not demonstrate actual simultaneous
FPGA compiler execution; tests cover the 78-GiB concurrent-search policy.
Routing and board timing are not yet complete.

## Search RTL Elaboration Failure

`g-search-hls-v2` reached synthesis but failed before executing RTL stimuli.
The generated `AESL_axi_slave_control.v` declares `write_binary_count` twice;
XSim reports `VRFC 10-2934` and no simulation snapshot. This is a generated
testbench elaboration failure, not an observed wrong output or accepted RTL
pass. The raw project, logs and source hashes are retained. A corrected
candidate needs a fresh attempt; generated failed evidence is not patched.

The synthesis log also reports II=2 for the dependent binary-search worker
loop. The finite-search model separates request and response phases, each
evaluated once per cycle. An II number alone does not establish their timing
difference: inspect response-to-next-request scheduling, FIFO handshakes and
transaction latency before promoting model timing as matching this HLS.

## Search Retry And Concurrent Admission

The retry changes only the top-level pointer name from `binary` to
`binary_nodes`, including its AXI pragmas. The original name combined with
the scalar `count` produced the generated testbench's duplicate
`write_binary_count` identifier. Neither the failed generated RTL nor its
source archive is edited. The fresh source controls are in
`g-search-controls-v3`; HLS/RTL must consume that complete, hash-checked control
set in a separate `g-search-hls-v3` attempt.
The HLS attempt separately freezes the actual synthesis/admission/analysis
runner and shared execution helpers; the source-control archive's older
runner copy is not relabeled as the code used for this retry.

The retry also removes the search supervisor's historical serial-cache gate.
It accounts for the cache's 6-GiB budget if still active, the route's 40-GiB
budget, its own 8-GiB tool budget, 24 GiB system reserve and the explicit
6-GiB R-study reserve. The current launch threshold is therefore 78 GiB with
cache finished, or 84 GiB with all three tools active. This changes admission,
not the functional or performance acceptance criteria.

The retained v2 synthesis estimate is 6.681 ns, above the 5-ns target. Its
reported critical path passes through round-robin request arbitration and
the dynamically selected FIFO read. Merely fixing the testbench identifier
does not fix that path or the worker II=2 schedule. They remain explicit
timing gates even if the retry's RTL output checks pass.

The fresh source controls subsequently completed all 38 executions (152 CU
checks) and the 18-call testbench-source check without errors. Their status is
`FINITE_HLS_SOURCE_PASS_NOT_RTL_TIMING`, not a hardware timing pass.
`g-search-hls-v3` then started under invocation
`df876ada7f0447c2bca0ace431570777`, while both the adapter route and R credit
study remained active. Its admission record measured 155826245632 available
bytes (about 145.1 GiB), exceeding the 78-GiB threshold. The actual HLS scope
has an 8-GiB hard bound, 7-GiB high bound and no swap; the 512-MiB supervisor
is separate. C simulation passed and synthesis started. RTL, clock and
complete-G acceptance remain open until their reports are checked.

## Search Arbitration Candidate

The retained v2/v3 source uses a variable rotate, priority encoder and cursor
adder before a dynamically selected FIFO read. A separate candidate encodes
the first ready absolute lane and the first ready lane at or after the cursor
in parallel, then selects the wrap or forward result. It leaves FIFO depths,
credits, worker searches, AXI bundles and ordered publication unchanged.
The existing source and RTL testbenches both exhaustively check all 255
nonempty ready masks and eight cursors against a scalar round-robin oracle
(2,040 combinations). The zero mask is not a valid call: both gather stages
guard selection with `ready != 0`.

The arbiter-only candidate is archived as `g-search-controls-v4`, not an edit
to the v3 archive. All 38 executions / 152 CU controls and eighteen testbench
source calls passed. It needs its own HLS/RTL before any clock improvement
can be claimed. It leaves the binary-search worker unchanged; the explicit
handshake candidate below supersedes it for the next HLS attempt. Arbitration
feasibility and model schedule alignment remain separate gates.

## Explicit Search Handshake Candidate

The v3 retry passed elaboration and entered RTL simulation, then hit its
1,800-second tool timeout. Its retained `results.json` records
`FAILED_RETAINED`, `timed_out: true` and exit code -9. The log completed only
the first two empty transactions, not a nonempty transaction. In
`bin_search_pipeline_search.v`,
`requests_63_write_local` in state 3 requires `ap_block_state3 == 0`, while
`ap_block_state3` includes `responses_63_empty_n == 0`. Thus the initial row
request is held until a response is already present. Initially empty response
FIFOs create a circular wait; the bounded attempt is retained without calling
its source controls an RTL pass. The inner binary-search loop also separates
response capture and dependent arithmetic, so its reported II cannot serve
as a blanket simulator timing multiplier.

A fresh candidate in `search_worker.hpp` explicitly separates input, row
request, row response, binary request, binary response, result and end phases.
Each iteration performs only its current phase's FIFO operation. It preserves
the search algorithm, one outstanding request per context, ordered results,
lane credits and FIFO capacities. Its source controls and fresh HLS/RTL must
pass independently; synthesis scheduling and the clock gate remain open.
The production G source and cycle engine are unchanged by this isolated test.

The fresh attempt is supervised by
`spine-grasu-search-candidate-20261016-v5.service`, invocation
`5434af73b3c7463d9c07cf4e35622012`. Its `g-search-controls-v5` source matrix
must complete successfully before systemd starts `g-search-hls-v5`; failure
skips that dependent HLS invocation. The supervisor is limited to 512 MiB,
no swap and two hours. Controls retain their 2-GiB bound; HLS retains its
8-GiB bound and 1,800-second tool timeout. HLS admission reserves 16 GiB for
concurrent studies and their supervisors, in addition to any active route's
40 GiB and the 24-GiB system reserve. With route active and cache complete,
the threshold is 88 GiB. Launch measured about 139.9 GiB available.

The new handshake candidate separately passes all eighteen small C++14
testbench-source calls and the 65 focused Python regressions. Their raw
records are under `verification-handshake-v5/` in the campaign root. These
are source/harness checks, not successful RTL simulation, 5-ns closure or
whole-G admission. The complete source matrix subsequently passed all 38
executions / 152 CU checks and eighteen testbench-source calls. The dependent
HLS started with 151547801600 bytes available (about 141.1 GiB), exceeding
its full 88-GiB admission threshold while the adapter route remained active.
C simulation and synthesis completed; the clock estimate is 6.225 ns, above
the 5-ns target. RTL co-simulation remains running at this checkpoint.

## Weighted Search Composition

While the search timing gate runs, the fresh `g-weighted-finite-v1` source
composition passes all twenty declared rows / 1,364 physical edits. It connects
the frozen explicit-handshake search candidate to the current weighted host
layout, dispatch, both pristine/registered cache-edit helpers and both adapter
modes. The additional 260-operation replacement sequence exercises reuse of
all 64 contexts. Each ordered search packet matches the pristine unit and
independent oracle; all 339 internal FIFOs, the bounded output, exact metadata
request ledger and complete intermediate PMA state are checked. See the
[weighted guide and portable evidence](../weighted_abi/README.md).

The attempt ran concurrently with the R study and adapter route, using a
2-GiB hard/no-swap scope, 180-second per-command timeout and 88-GiB reserve
(90 GiB total admission threshold), with over 141 GiB available. Its separate
512-MiB supervisor has a 900-second lifetime. Both adapter arms execute
sequentially on CPU 126. This does not require waiting for FPGA compilers to
exit when full budgets fit.

This closes an additional weighted source-compatibility question, not the
production eleven-argument search binding, concurrent cache/DDR pipeline,
metadata refresh, new-G routing, board timing or publication-performance gate.

The portable weighted capsule and the search/structure regression suites pass
79 focused Python tests. Their bounded resource record is in
`verification-weighted-finite-v1/`, using a 2-GiB/no-swap scope and 88-GiB
reserve. CPU test wall time is not a measured accelerator latency.

## Routing Watchdog Recovery

`r-adapter-route-v2` stopped during block synthesis at 141 of 302 jobs. Its
supervisor reports `Too many open files`, not a design/timing or memory-capacity
failure. The pidfd watchdog retained descriptors for terminated compiler
workers; 1,018 observed PIDs exhausted its file-descriptor limit. The retained
resource record reports 16,202,300 KiB peak sampled tree RSS, more than 132 GiB
minimum system memory available, and no cgroup OOM/max/high events. Cleanup
terminated only the owned build workers. No successful bitstream was produced.

The corrected watchdog closes signaled exited pidfds during each observation
and retains PID history separately. Tests exercise 2,048 exited workers without
descriptor growth, safe PID reuse, nested-session cleanup and failed final
snapshots. All 28 cleanup, route and memory-admission tests pass. No hardware
source, numerical model, memory budget or link acceptance criterion changes.

The fresh `r-adapter-route-v3` retains the eleven XOs and 150-MHz configuration.
Its six environment preflight checks pass. Invocation
`d4ef573e40cc4f2cb52e4d13856965d5` reuses the service label reserved by the live
search/R studies, with a new attempt directory and source pins. It reserves
40 GiB for routing, 24 GiB for the system, 8 GiB for background studies and
the full cgroup limit of each concurrent FPGA tool. With one 8-GiB search
scope active, the threshold is 80 GiB. The original failure remains intact;
the replacement is a running experiment, not routed or board evidence.
