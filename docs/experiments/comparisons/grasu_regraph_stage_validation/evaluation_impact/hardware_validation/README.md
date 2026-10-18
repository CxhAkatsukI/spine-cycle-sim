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

The [full-graph host-readiness check](fullgraph_readiness/README.md) owns a
separate offline prerequisite: unchanged production hosts, six-partition
smokes and all 24 frozen eight-graph/three-algorithm inputs. Its memory queue
admits work when complete budgets fit, not when all FPGA tools have exited.
CPU-oracle/layout preparation must not be reported as FPGA timing, actual
new-G metadata/handoff correctness or original-publication reproduction.

## Current Checkpoint

The [original-G hardware control](original_grasu/README.md) now has a separate
source-preserving build owner. It retains the author's URAM cache, all 46
memory interfaces and exact kernel files; it does not substitute the older
modified G+R bitstream. The same-platform U55C/150-MHz control remains
distinct from reproducing the U250 publication. Preparation/ABI unit tests
are not integrated RTL, board timing or original-performance admission.

At the 2026-10-18 12:34 UTC checkpoint the original-G link has failed: all
four author kernel types compiled, but 46 AXI masters exceed the platform's
33 HMSS ingress connections. This is an interface/platform limitation, not
an OOM or measured performance result. The independent
[same-input production-G control](original_grasu/matched_production/README.md)
passes all eight original cases in both Release and UBSan (22 child steps).
It preserves the logical PMA/reservation/update sequence and validates the
real production layout; it has not yet measured paired FPGA performance.
Its separately owned board launcher and exact-qualifier continuation now
require complete state and raw timestamp replay for all eight inputs with
three repetitions. These execution/guard tests are not a completed FPGA
matrix; original G's platform-port failure still blocks a paired speed match.

The independent [external metadata fan-in diagnostic](original_grasu/physical_port/README.md)
preserves all author masters and shares same-bank metadata outside the CUs.
Its first two actual BD attempts failed on a clock-name/object API call and
then a missing interface-connection endpoint. Both are retained tool-script
failures, not OOM or measured slowdowns. BD v3 subsequently exposed a stock
HMSS callback's single-addressing-master assumption. Frozen BD v4 then failed
at 14:31 UTC because the discovery callbacks loaded before its future-source
trace; neither discovery lookup was adapted. There were zero OOM events.
Its exact full-link v3/return v3 continuations consequently stop before tools
or programming. A correction now discovers already-loaded callbacks as well
as later loads, while preserving vendor diagnostics and installed files.
A fresh actual BD pass is still required. BD v5, full-link v4 and return v4
pin immutable runner `ad8f81e` and exact parent invocations. At 15:03 UTC,
BD v5 ran but rejected SDx's unrelated same-named callback after adapting the
two intended HBM callbacks. Its dependent attempts stop before tools or
programming. A targeted correction preserves only that reviewed SDx callback
unchanged and still requires exactly two adapted HBM callbacks. The linked
guide records the retained failures and fresh-retry requirements. Existing
admitted SSSP/CC/FullPR routes and ResPR refinement continue concurrently.
The linked diagnostic guide owns its
runner, invocation, archive hash, tests and separate acceptance boundary.
Its separate return receipt/offline replay and strict routed admission are
now implemented. The discovery corrections bring the original-G regression
suite to 124 tests. The changed external
interconnect stays explicit throughout return and board profiles. Tests and
deployment do not establish routing, measured performance or publication match.

The [original-R arithmetic audit](original_regraph/arithmetic_control/README.md)
now completes all six layouts and twelve explicit divisor bindings. Original
11+3 and A4 arithmetic reports agree. A candidate common single-superstep
profile uses numeric binary32 input contributions, damping `108/128`, zero
base/dangling correction and the CSR-degree divisor. On Amazon, median numeric
payload difference from the author's fixed-point output is 0.438% on nonzero
fixed outputs, but this is not bitwise equivalence or default production PR.
The author-initial divisor has materially different truncation effects and
remains reported. This offline audit does not execute candidate HLS, measure
adapter/K4 performance or admit any replacement figure. An actual matched
adapter/K4 board control is still required.

At the 14:19 UTC tool check, the high-memory host has 395 GiB available.
SSSP v2 continues routing optimization, CC v2 is in placement,
and FullPR v2 has entered implementation, each under its own 40-GiB hard limit.
ResPR v2 completed v++ but fails strict setup timing
(WNS -0.107 ns, TNS -18.575 ns, 443 failing endpoints), without OOM events.
Its returned DATA/HBM clocks are 147/434 MHz, rather than 150/450 MHz;
the return gate rejects it before board programming. A separately owned
checkpoint diagnostic has now entered Vivado and loaded the exact routed
checkpoint. It tests physical refinement without changing HLS/clocks or
producing a bitstream. It is running, not timing-closed or board-admitted.
At that checkpoint, admitted tools retain
40/36-GiB max/high, zero swap and group-OOM containment. New compiler
admission can be blocked by an unrelated unbounded vendor RTL simulation,
not by a requirement that all bounded FPGA jobs exit. No other user's
process is changed.
FullPR v1 also remains a timing/clock failure; its v2 retry and
exact return/board continuations are separately frozen.
The fullgraph v7 waiter and its paired v4 child stopped before requesting a
board because that matrix includes the rejected ResPR return. The replacement
[v8 continuation](fullgraph_readiness/README.md#current-continuation) retains
that rejection while allowing independently admitted SSSP/CC matrices to run;
it cannot declare the complete three-algorithm gate passed. At deployment it
is waiting, without a board request. Matched-G v1 also stopped before
programming because its preflight pinned three subsequently changed files in
the development checkout. Fresh original-G v4 and matched-G v2 preflights now
pass all eight inputs from an immutable `f50a185` snapshot. The new matched-G
board follower pins both complete reports and waits for the exact production
SSSP qualifier. Its deployment is not a measured G performance match. All
earlier failures are retained; timing and changed-pin gates remain unchanged.
The [algorithm guide](complete_pipeline/production_routing/algorithm_build/README.md#physical-timing-retry)
owns the failed report, retry identity and live-state boundary. The earlier
resume narrative below is historical where it differs from this checkpoint.

### High-Memory Host Resume

The 2026-10-17 resume found both old routes terminal: diagnostic G v2 linked,
and A4 v2 passed strict 150-MHz routed timing (WNS +0.003 ns, WHS +0.009 ns).
Production route v1 and metadata-host v1 stopped before launching a compiler
because their bounded `ps` query timed out; these are retained startup failures,
not completed builds. The fresh metadata-host v2 passes compilation, all
three same-address metadata generations, and the stale-metadata negative test.
This remains CPU host-model evidence, not device refresh admission.

A4 board v2 stopped before programming because fresh topology tuples were
compared with their JSON list representation. The checker now normalizes the
fresh observation through JSON before exact comparison; ABI, clock, bindings,
binary identity and strict timing remain unchanged and independently checked.
Diagnostic G board v4 reached programming but XRT rejected the occupied device
(`Device or resource busy`); no computation/performance result was obtained.
Neither failure is silently retried or rewritten.

The fresh A4 board v3 completes all eighteen declared FPGA rows, with zero
memory events. This is a same-platform one-superstep PR control, not dynamic
convergence or original-paper performance reproduction. The production route
continues separately through the [high-memory host package](complete_pipeline/production_routing/remote/README.md).

Diagnostic G/GR board v5 now passes its 18 G / 27 resident G+SSSP executions
(54 / 81 batch rows), with zero memory events. It uses the older diagnostic
search/cache exports. Production SSSP is actually building on `seele`, not
merely queued: all six environment checks passed and block synthesis began.
Its return/strict-timing/three-matrix board continuation has a separate owner
in the linked remote package. No production FPGA result, published-performance
match, fixed-Spine matrix or replacement figure is claimed yet.

Fresh CC / FullPR v1 and ResPR v2 compilations have completed. Their separate
40-GiB experimental links remain active. SSSP v1 has linked, but its final HBM
setup timing is negative and Vitis downclocks that domain; the return is
rejected, not used for board comparison. A physical-only v2 retry retains all
XOs, topology, target clocks and strict timing checks. Its separate return and
v4 full-graph continuation name the exact fresh invocations. At the 08:45 UTC
checkpoint the remote host has approximately 400 GiB available; owned jobs
retain finite 40-GiB limits and zero swap. All three fresh algorithm adapters pass their own 23-case
AXI/AXIS RTL trials. Those adapter-only passes are not whole-algorithm RTL or
device results. The [algorithm-specific guide](complete_pipeline/production_routing/algorithm_build/README.md)
owns the source identities, retained failed attempts, resource screens and
return/admission procedure. Figures 7--11 remain unreplaced.

The full-graph host's new PCIe-BDF guard fails before context creation when
the chosen card differs from the exclusive lease. All three negative checks
pass with the explicit XRT runtime environment; an earlier environment-failure
attempt remains a failed harness. A fresh offline v3 rechecks integration
`1a5650c` on the complete matrix and has completed all three smokes and 24
preparations, with zero memory-limit/OOM events. This is an offline pass only.
The [full-graph guide](fullgraph_readiness/README.md#board-continuation) owns
the separate serial board continuation, exact prerequisite invocations and
resident-update timing definition. This prepares only the new G+R arm;
original-G/R performance decisions and the fixed-Spine comparison are separate.

Fixed-Spine SSSP v2 has now completed both correctness smokes and all eight
full graphs with three repetitions: 26/26 FPGA executions pass. Its continuous
resident wall medians are 95.4--185.8 ms, including actual host relaunch and
per-round full-state readback. The service exits successfully; peak memory is
18.6 GiB with zero memory-limit/OOM events. An independent raw-output replay
passes all 26 executions and 626 pins. The [Spine protocol guide](fullgraph_readiness/spine_resident/README.md#completed-sssp-matrix)
retains the individual times and exact identities. CC v2 and residual PR v2
also complete 26/26 executions each, with independent raw replay and zero
memory-limit/OOM events. All eight large ResPR cases perform zero propagation
launches at the frozen activity threshold; their wall time still includes
maintenance, host degree/correction/seed work and final readback. They are not
evidence of large-graph residual propagation performance.

The independent [FullPR protocol](fullgraph_readiness/fullpr_resident/README.md)
retains two failed Spine board attempts. Its G+R true-convergence CPU/board
entry is now implemented with explicit AU/SU/WK scope, but no successful
FullPR paired matrix is claimed. The complete new-production G+R matrix is
still waiting for routed admissions. No new paired speedup or final figure
is claimed.

### Historical 2026-10-16 Track Snapshot

The table below retains the earlier campaign checkpoint. For subsequent A4,
diagnostic G/GR and remote-production changes, use the current checkpoint
above and its owned guides rather than interpreting these old queue states
as live status.

| Track | Latest evidence | Remaining gate |
| --- | --- | --- |
| Cache | Original/candidate complete hot-half controls pass paired C simulation, synthesis and six RTL transactions | Integrate both halves with cold DDR, search and metadata refresh; check complete resource fit |
| Search | Fresh v11 passes all eighteen C/Verilog transactions; 3.650-ns isolated estimate | Timing-model alignment, integrated RTL and board gates; earlier failures remain retained |
| Search host binding | All 216 source calls and eighteen real-wrapper RTL transactions pass; independent canonical-XO review matches the routed ABI, with a 3.650-ns estimate | External RTL backpressure, production integration, routed clock and board execution |
| Weighted composition | Twenty finite-search source rows / 1,364 physical edits pass | Concurrent complete-G HLS, coherent metadata lifecycle and board timing |
| Complete G source | Twelve synthetic rows replay exactly; 42 additional real host-prepared rows pass complete-state/direct-adapter checks | Integrated RTL/backpressure, actual XRT bindings, resource fit and hardware timing; internal cache/DDR C-simulation FIFOs remain unbounded |
| Native multi-shard/cold G source | Six paired-arm rows pass at full 131,072-segment cache capacity, five native 65,536-vertex shards, and persistent empty/delete/insert batches; portable raw-row replay is delivered | Functional source coverage only; native cold/multi-shard XRT binding, integrated RTL and board measurements remain open |
| Native five-shard G XRT extension | Fresh XRT compilation, eighteen deterministic old host-model rows and three native host-model rows pass; fresh six-row source regression exactly matches the earlier setup/numerical results; both portable capsules retain raw evidence and the v3 thread-limit failure | CPU/source equivalence closed only; actual native board state/timing and same-address metadata-generation refresh remain open; see the [extension guide](complete_pipeline/native_board/README.md) |
| Continuous G host | Device-guarded XRT host compiles; eighteen host-model rows match the earlier state checks; bounded board launcher rejects a live unfinished route before programming | Board path not executed; real runtime/event checks, cold/multi-shard/metadata checks and actual timing remain open |
| Continuous G-to-SSSP host | 27 host-model batch rows replay unchanged with device identity guards; bounded launcher and kernel/DMA/convergence event checks pass regressions and reject the live unfinished route before programming | FPGA matrix not executed; routed timing admission, actual handoff/runtime measurements and larger/cold/multi-shard scope remain open |
| Cache production binding | Shared-core extraction passes all twelve composition controls again; production wrapper passes six full-state RTL transactions, token checks and exported ABI at a 3.650-ns estimate | Complete-G resource fit, integrated RTL/backpressure, production integration, routing and board timing |
| Opt-in production G source | Production candidate through `bc40a31` is committed/pushed; functional v5, HLS v3 and production RTL v2 pass 18 search, 6 token-cache and 6 plain-cache transactions and exported ABI checks; fresh read-only production-source re-admission passes with a 4.867-ns isolated estimate at the rounded 6.67-ns target | Component RTL only: integrated metadata/backpressure, full resource/timing and external UDF gates remain open; v1's header-flag parsing failure is retained. This is not the frozen diagnostic-route input |
| Production storage screen | Fresh production exports sum to 768 URAM / 1132 BRAM_18K; original placement overfills SLR0 (384 of 320 URAM), while relocating only the fourth Little CU gives 320 / 128 / 320; a separate portable [resource capsule](complete_pipeline/resource_evidence/README.md) is delivered | Storage feasibility only, not full resource/timing closure or production route/board admission |
| Connected production G host | Eighteen connected search/dispatch/full-cache/cold-DDR transactions pass complete six-buffer state, finite external stalls and conservation; the deliberate stale-metadata control is rejected at the declared transaction; the [production-owner capsule](complete_pipeline/production_integration/README.md) retains the failed diagnostic-analyzer attempt | Host functional evidence only: internal cache/cold streams remain unbounded; integrated RTL/backpressure, real device-BO refresh, adapter/R handoff, same-version route and board timing are not admitted |
| Production-source experimental route | Fresh [production packet](complete_pipeline/production_routing/README.md) rechecks production RTL/ABI, connected state, reused upstream XOs and same-export storage; integration `7b3763e` / simulator `1006b7f` are frozen. At 2026-10-16 09:02 UTC it is queued, not routing, alongside two active bounded routes | Full-budget memory admission, completed artifact and strict timing; integrated RTL, actual device metadata refresh, PMA handoff and production board performance remain unadmitted. The old diagnostic board queues do not validate this packet |
| Production board qualifier | [Dedicated production gate and matrices](complete_pipeline/production_board/README.md) require exact route/metadata-host invocations, complete artifact/timing checks and unchanged numerical validators; 124 relevant regression/organization tests pass. Frozen runner `e392b5e` is queued at 09:52 UTC with 2960 pins, no programming and no errors | No production FPGA matrix has run. Native cold/multi-shard, same-BO metadata refresh and resident G-to-SSSP checks must all pass; qualification is not publication-performance reproduction |
| R controls | All 28 rows complete and twelve legacy rows replay exactly; candidate is 2.949--3.635x slower than `a4_io16` | Explain/address the resource-sensitive gap; separate hardware/publication decisions |
| Original-R hardware preflight | Six frozen author-input audits pass gather conservation; apply-divisor and mixed-output allocation controls are explicit; prebuilt metadata reports DATA 215 MHz | Source/clock/checkpoint pairing, guarded original-R board host and measured performance; no publication or board admission |
| Adapter routing | `r-adapter-route-v3` generated an xclbin; final HBM setup slack is -0.032 ns and fails timing admission | Timing closure and board gates remain open; the link exit code is not timing admission and this is not a complete-new-G route |
| Diagnostic G storage/link | v1 timed out during bitstream generation after nonnegative final routing timing, with no completed xclbin and zero OOM counts; twelve-hour v2 is building concurrently with the A4 retry after full-budget admission | Completed artifact checks and diagnostic board correctness/timing; this older search/cache-export route does not admit the current production-G candidate |
| Conditional G/GR board queue | v1 stopped on route timeout; v2 rejected a changed preflight manifest; v3 was deliberately stopped while waiting, before programming, to set the XRT environment explicitly. Fresh v4 pins the same final manifest and waits for the exact G v2 invocation | Six-input G and nine-input resident G-to-SSSP board matrices remain unmeasured; no source pins or timing gates waived; diagnostic evidence only |
| Original-R source and board | Fresh independent ABI/HBM/AXIS/clock/strict-timing review passes v6's exact 150-MHz artifact (WNS +0.002 ns, WHS +0.009 ns, zero failures); original analyzer failure remains untouched. Fresh board v4 passes all eighteen output/timing rows, packaged with two failed startup attempts in the [board capsule](original_regraph/board_matrix/README.md) | One static PR superstep only: publication reproduction, convergence, A4 and actual adapter/K4 comparison remain separate gates |
| A4 source path | First artifact's global HBM WNS -0.098 ns fails admission. Fresh Apply-to-SLR0 retry `a4-source-route-v2` has compiled all four XOs and is now building concurrently with diagnostic G, preserving algorithm, HBM/AXIS mapping, clock and strict signoff | Not board-admitted; terminal artifact/topology/strict timing and actual board matrix still required. The retry is a physical-placement control, not the author's physical configuration |
| A4 board path | `original-r-xrt-host-validation-v1` compiles exact Xilinx-linked Release/UBSan hosts and passes all 48 offline rows for both ABIs. Fresh A4 board queue v2 explicitly sets XRT environment and waits for the exact retry route | Eighteen actual A4 board rows remain unmeasured; historical 11+3-only hosts and the completed 11+3 board matrix cannot authorize A4 |
| Full-graph host readiness | At 2026-10-16 03:42:23 UTC, v2 completed all three smokes and 24/24 preparations with zero errors/OOM events; the portable capsule retains both v1's diagnostic-gate failure and v2's pass; 30 focused tests and 15 organization tests pass | Offline CPU-oracle/layout prerequisite closed only; actual board timing, new-G metadata/handoff and publication comparisons remain open |

This is a progress checkpoint, not an admission of the complete baseline.
The [original-R preflight guide](original_regraph/README.md) owns the six-input
offline audit and subsequent eighteen-row board capsule. Its PR divisor/allocation findings and
230-to-215.1-MHz auto-scaling record must be addressed explicitly before a
board comparison; they are not measured PMA/K4 overhead.
The [complete-G source guide](complete_pipeline/README.md) owns its portable
evidence, exact scope and retained failed attempts.
The [host-prepared guide](complete_pipeline/host_prepared/README.md) separates
the AU/SU/WK source matrix from native hardware capacity and performance.
The [continuous-host guide](complete_pipeline/continuous_board/README.md)
defines isolated G-ready timing separately from complete G+R convergence;
its preflight does not invoke FPGA APIs. The
[board execution guide](complete_pipeline/continuous_board/execution/README.md)
separates the delivered launch guards from the still-unexecuted G/GR FPGA matrix.
Its conditional queue now runs under bounded memory and waits only for the
required bitstream, not unrelated FPGA tools. Failure stops the queue without
board reset/retry; a queued matrix remains unmeasured.
The [G-to-SSSP handoff guide](complete_pipeline/continuous_handoff/README.md)
owns the convergence preflight, warm/fallback policies, original-G regression
and retained failed parser attempt; it is not a board measurement.
The [diagnostic G-link guide](complete_pipeline/hardware/README.md) records
the new search/full-cache XO substitutions, single-CU placement change,
atomic full-budget concurrency policy and monitoring commands. The
[resource capsule](complete_pipeline/resource_evidence/README.md) preserves
the physical/platform queries, including the timed-out attempt; storage-site
headroom is not claimed as completed resource or timing closure.
The [cache-wrapper evidence index](cache_binding_evidence/index.json) freezes
the completed concurrent wrapper check, including its exported XO and both
reference interfaces. Verify it from the worktree root:

```bash
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.binding_delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/cache_binding_evidence"))'
```

The following sections preserve the earlier attempts and explain each current
candidate. All concurrent launches reserve full bounded memory budgets; other
FPGA tools need not exit when those budgets and the system reserve fit.

## Wrapper RTL And Retained ABI Review

`g-search-binding-rtl-v1` completed C simulation, synthesis, all eighteen
RTL transactions and XO export with tool exit code zero. Its first analyzer
retains `FAILED_RETAINED`: it incorrectly treated a Vivado scratch
`.Xil/.../.kernelxml/kernel.xml` inside the XO as a second exported kernel ABI.
This is an analysis failure, not a failed RTL transaction. The old result and
its frozen runner are unchanged.

The independent `g-search-binding-abi-review-v1` selects the unique canonical
`bin_search/kernel.xml` and direct `ip_repo/<ip>/component.xml`. It verifies
the old frozen sources, runner, logs, reports and XO, and rejects a changed
non-ABI observation. No new hardware simulation is claimed by this review.
Its decision is `WRAPPER_RTL_ABI_PASS_TARGET_MET_REQUIRES_INTEGRATION`:

- All eighteen transactions pass, covering counts 0, 1, 63, 64, 65, 127, 128,
  129 and 257, each with two metadata generations at reused pointer addresses.
- The exported eleven arguments, 23 registers, `ap_ctrl_chain`, 96-bit AXIS
  payload and 12-bit keep/strb sidebands match the existing routed search ABI.
- Synthesis estimates 3.650 ns, 77,465 LUTs, 70,448 FFs, four BRAMs and no URAM.
  These are component estimates, not routed timing or complete-G area.

The XO SHA-256 is
`d57b5827e2bbb09614e4bcd95fbe97adc79721db05e567820b6a9ac50eb39f1f`.
The raw attempt and independent review live under the campaign root above.
The [search guide](../search_pipeline/README.md#production-wrapper-rtl-and-abi)
owns reproduction commands and the remaining gates.

The isolated v10 bench used a default function pointer, which vendor
co-simulation failed to instrument (`212-330`, top not invoked). The fresh
v11 bench invokes the top directly through an explicit lambda. It changes
neither the hardware implementation nor the test vectors/oracle. Its source
and RTL retry are separate from the successful real-wrapper evidence.

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
the 5-ns target. RTL co-simulation subsequently hit its 1,800-second timeout,
with no completed nonempty transaction. The terminal result is
`FAILED_RETAINED`, not a passing RTL result.

## Nonoverlapping Search Worker Candidate

Inspection of the v5 generated RTL reveals another scheduling risk. Its
pipelined worker loop can overlap a request write from one iteration with a
response read from the next. The shared pipeline-block signal includes the
empty response FIFO and gates the preceding request write. Separate C++ switch
cases therefore do not by themselves establish an independent RTL handshake.
The v5 source and generated reports remain frozen. Its eventual timeout is
recorded above, separately from this source-level scheduling diagnosis.

The fresh v6 candidate disables loop-iteration pipelining inside each search
context. All 64 contexts still execute concurrently. Response capture, row
decode, binary comparison, midpoint arithmetic and next-phase selection use
distinct explicit states. FIFO depths, metadata credits, search semantics,
ordered publication and external interfaces are unchanged. This is a candidate
RTL scheduling change, not a demonstrated clock or latency improvement.
The simulator cycle engine and production G remain unchanged; alignment to
this worker's actual RTL schedule is a separate gate if it passes.

`spine-grasu-search-candidate-20261016-v6.service`, invocation
`e24fa09375a44a26bef74720ffee00d0`, runs the complete source matrix under
`g-search-controls-v6` before a dependent `g-search-hls-v6` attempt. Failed
source controls prevent HLS from starting. The supervisor has a 512-MiB hard
bound, no swap and a two-hour lifetime. Source commands retain their 2-GiB
bound; HLS retains 8 GiB hard / 7 GiB high, no swap and a 1,800-second timeout.
HLS admission includes 24 GiB background reserve for the concurrent old search
attempt, R study and supervisors, plus 24 GiB system reserve and the active
route's 40-GiB hard budget: a 96-GiB threshold with routing active. About
141 GiB was available at launch. An exited client used to start the transient
service does not terminate its separately supervised source or HLS processes.

Forty-nine focused search, weighted-composition, cleanup and repository
structure regressions pass with this candidate. All 38 source executions /
152 CU controls and eighteen C++14 testbench-source calls subsequently passed.
The dependent HLS run passed C simulation and synthesis. Its estimated clock
period is 5.572 ns, above the 5-ns target, with 77,132 LUTs, 69,935 FFs, four
BRAMs and no URAM. The synthesis report identifies the gather arbitration
feedback path: ready selection, dynamically selected FIFO read and the
finished-mask update. This is a specific timing failure, not closure of the
clock gate. RTL completion and timing-model alignment remain outstanding.

## Production-Shaped Search Binding

The production compact host sets eleven search arguments: the update buffer,
four binary pointers, four row pointers, update count and the implicit AXIS
stream. The four binary arguments alias one allocation; likewise the four row
arguments alias one allocation. The compact kernel reads only `binary_0` and
`row_offset_0`, on the same metadata AXI bundle. This is still shared metadata,
not the separate-copy layout that improves some earlier model predictions.

The new `search_binding` wrapper retains this pointer order, scalar width,
AXIS packet type and compact interface pragmas. Both isolated and binding
wrappers call one extracted `search_pipeline/network.hpp`; the search workers,
339 finite FIFOs, credits and publication order are unchanged. The wrapper is
a source candidate in this repository, not yet a replacement production XO.
Extraction requires its own replay and HLS check; passing the frozen v6 RTL
would not automatically validate the extracted hierarchy.

`g-search-binding-v1` passes all 216 declared C++14 source calls:

- Two metadata generations overwrite the same vector storage with different
  row extents and keys; there is no retained metadata snapshot between calls.
- Counts 0, 1, 63, 64, 65, 127, 128, 129 and 257 cover empty and context-wrap
  boundaries, with mixed-source and single-source updates.
- Actual aliased pointers, deliberately poisoned unused pointers and null
  unused pointers all give the same results and probe counts.
- Normal and stalled consumers check every ordered 96-bit result, finite FIFO
  conservation and exact metadata request/response counts.

The control took 79.14 seconds; its recorded maximum process RSS was 16,404 KiB
(not a simultaneous process-tree total). Compilation took 4.31 seconds and
343,196 KiB maximum process RSS. Both were capped at 2 GiB, no swap, CPU 125,
with an 88-GiB background/system reserve and separate 180/600-second timeouts.
The production host and kernel sources, vendor dependencies, compiler version,
candidate sources, raw output and resource records are pinned in the
[portable capsule](search_binding_evidence/index.json).

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding.study \
  --output /path/to/fresh-binding-control \
  --integration /path/to/grasu-regraph-integration \
  --hls-include /path/to/Vitis_HLS/2024.1/include
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/search_binding_evidence"))'
```

The separate `g-search-extracted-v1` is replaying all 38 large source controls
against the preceding metadata ledger. Neither source control checks XRT
argument offsets, generated registers, external AXI stalls or routed timing.
No complete-G, publication-match or hardware-timing admission follows. Both
cache halves, cold DDR, metadata refresh, complete resource fit and physical
G-to-R handoff still require integrated validation.

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

## Registered Gather And Feedback Progress

The shared-network extraction has a completed independent replay in
`g-search-extracted-v1`: all 38 source executions, 152 CU checks and eighteen
testbench-source calls pass. Ordered packet checks, per-CU probe counts and
339-channel conservation agree with `g-search-controls-v6`. Only host
blocked-write observations are excluded from equality because thread scheduling
is nondeterministic; they are never accelerator timing evidence.

The v7 candidate registers the selected FIFO before reading it in a subsequent
nonpipelined gather iteration. This separates the selector from the dynamically
selected FIFO read, which remained on v6's critical path. FIFO depths, credits
and the eight-by-eight topology do not change. Its potential added cycles must
be checked, not assumed free.

Inspection of v6's generated
`bin_search_pipeline_memory_Pipeline_VITIS_LOOP_60_1.v` identifies a separate
feedback-progress hazard. `ap_block_state1_pp0_stage0_iter0` includes empty
`memory_requests`; that condition also gates iteration-73 response publication
and the pipeline-register enables. A context waiting for its row response need
not issue another request. Blocking on the next empty input can therefore hold
the response it needs. The response scatter pipelines have the same input-empty
global-stall structure. The retained RTL log has only the two empty transactions
completed; this diagnosis is not a passing nonempty test.
The v6 attempt subsequently reached its 1,800-second timeout and records
`FAILED_RETAINED`, `timed_out: true`, exit code -9. Neither this termination
nor its source passes are hardware timing admission.

The fresh v8 candidate uses `read_nb` in the memory and two response-routing
loops so an empty input injects a bubble without stopping prior iterations.
Output writes remain backpressured and end tokens, tags, outstanding bounds,
AXI bundles and ordered results are unchanged. This is a physical scheduling
candidate; source tests alone cannot show that Vitis generated the intended
progress behavior. All eighteen RTL transactions, including a single update,
must complete, and the 5-ns estimate must pass separately. External RTL output
backpressure, wrapper ABI, production integration and simulator timing alignment
remain open even if these isolated checks pass.

`spine-grasu-search-candidate-20261016-v8.service`, invocation
`5d0631e1de18493dad6885bc3c64db5e`, freezes `g-search-controls-v8` before the
dependent `g-search-hls-v8`. It reserves 32 GiB for other simultaneous studies,
8 GiB for its tool, 24 GiB system reserve and any active route's full 40 GiB.
With cache finished and route active, the HLS threshold is 104 GiB. Available
memory at source launch was approximately 137 GiB. No other FPGA tool must exit
when these budgets fit; each actual tool launch rechecks memory. The supervisor
retains its 512-MiB/no-swap bound, and the HLS timeout remains 1,800 seconds.
No frozen earlier attempt, production kernel or simulator timing model is
rewritten by this retry.

## Shared Hierarchy And Host Polling Retry

`g-search-hls-v7` and `g-search-hls-v9` pass their eighteen C-simulation calls
but fail synthesis with `HLS 214-272`. The extracted `network` function has
both `INLINE` and `DATAFLOW`, while its outer top is not a dataflow region.
Vitis explicitly rejects this combination. Neither run reaches a new clock
report or RTL execution. The frozen source, logs and failures remain unchanged.

The new v10 source keeps `network` as `INLINE off` with its existing internal
`DATAFLOW` region. It preserves the registered gather and nonblocking feedback
candidate, stream capacities, search algorithm and argument interfaces. This
is a fresh synthesis-hierarchy candidate, not evidence that its RTL now works.
The host-only finite-stream delegate also unlocks and yields on empty polls;
that change prevents polling threads from monopolizing the affinity cores.
It is excluded under `__SYNTHESIS__` and is not a device-cycle optimization.

`g-search-controls-v10` must pass all 38 executions / 152 CU checks and eighteen
testbench-source calls before its dependent `g-search-hls-v10` can start.
The 512-MiB/no-swap supervisor is bounded to two hours. HLS retains its
8-GiB/no-swap bound and 1,800-second timeout; routing plus background reserves
raise the current admission threshold to 112 GiB. Approximately 141 GiB was
available at source launch. This policy permits actual concurrent tools.

The matching `g-search-binding-v4` already passes all 216 source calls using
the v10 network, actual pointer aliases, two metadata generations, poisoned/null
unused pointers and stalled consumers. The new production-wrapper RTL/ABI probe
is documented in the [search guide](../search_pipeline/README.md#production-wrapper-rtl-and-abi).
It requires both complete source reports and identical frozen shared sources;
exported XO metadata is compared to the old routed wrapper's register/AXIS ABI.
Parser tests are not a generated-ABI or RTL pass. Nonempty RTL, clock feasibility,
external RTL backpressure, integrated G, simulator schedule alignment and board
measurement remain distinct open gates.

The v10 matrix subsequently completed all 38 executions / 152 CU controls and
eighteen testbench-source calls without errors. `g-search-hls-v10` passed C
simulation and entered synthesis. Its admission recorded 154955149312 available
bytes (about 144.3 GiB), above the 112-GiB threshold. The separate
`g-search-binding-rtl-v1` invocation `5f3220fdc11c4a489c8fd4a726a0a654` also
entered HLS while routing remained active, recording 154336993280 available
bytes (about 143.7 GiB). These are actual concurrent launches, not queued passes.

Seventy-five focused regressions pass; their complete command, stdout/stderr
and resource record are under `verification-wrapper-rtl-v3/` in the raw campaign
root. The process tree is capped at 2 GiB with no swap, CPU 123, a 180-second
timeout and 112-GiB admission reserve. Earlier verification attempts are
retained: v1's inherited 2-GiB address-space hard limit prevented two watchdog
test children from setting their own virtual-address limit; v2 found that GNU
`time` is not installed. The v3 cgroup bound preserves the same 2-GiB physical
memory budget without imposing that incompatible inherited virtual limit.
No watchdog assertion, RTL gate or hardware resource bound was relaxed.
