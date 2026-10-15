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
loop. The previous finite-search model assumed one-cycle stage issue, so its
timing cannot yet be promoted as matching this HLS schedule. Both the
elaboration problem and schedule difference must be resolved explicitly.

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
