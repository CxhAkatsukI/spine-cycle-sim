# Registered Comparison Candidate

## Scope And Decisions

This is the current-candidate navigation page, not a hardware-performance
acceptance. Historical attempts in the parent guides remain frozen. Local raw
outputs are under
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/` (LROOT);
remote outputs are under
`/data/chuxiao/baseline_hardware_validation_20261017/` (RROOT), on
`ssh -p 23333 chuxiao@10.129.161.241`.

| Gate | Current evidence | Meaning |
| --- | --- | --- |
| G functional, connected-state and component RTL | `g-cache-comparison-{functional,connected,rtl,readmission}-v1` | Passing component checks; not integrated RTL or FPGA timing |
| G cache simulator/RTL service increments | `g-cache-model-timing-v2`; [raw data and scope](../../../../cache_probe/README.md#same-stimulus-simulator-service-control) | Balanced 1 cycle/update in both; same-bank extra cost 2.006836 vs 2.005371 cycles/update; not total-time calibration |
| Fresh CC, ResPR and FullPR compilation | `production-cc-compile-local-v2`, `production-respr-compile-local-v2`, `production-fullpr-compile-local-v1` | All compile; not routed timing or device correctness |
| Fresh CC and ResPR adapter RTL | `production-{cc,respr}-fresh-adapter-rtl-v1` | Both pass; not complete-algorithm RTL or board performance |
| Fresh FullPR adapter RTL | `production-fullpr-fresh-adapter-rtl-v1` | Passes separately; not complete-algorithm RTL or board performance |
| New SSSP link and qualification | RROOT `g-cache-comparison-route-v2`; LROOT `g-cache-comparison-remote-follow-v2` | Routing; pending strict return admission and board qualification |
| New CC link and strict return | `production-cc-compile-route-local-v1`; `production-cc-local-return-v1` | Bitstream, source/topology and setup/hold/pulse timing admitted; FPGA convergence/performance remains pending |
| Remote ResPR/FullPR build chains | RROOT `production-{respr,fullpr}-compile-v3` and `production-{respr,fullpr}-compile-route-v3`; LROOT `production-{respr,fullpr}-remote-return-v3` | Fresh bounded compiles and exact compile-to-route-to-return followers; no admitted artifact yet |
| Full-graph new-G+R performance | [Exact request file](fullgraph_requests.json) | Not yet accepted; requires successful returns and board runs |
| Paired resident replay | [Exact paired requests](paired_requests.json) | Binds the v13 producer's three new admissions to the unchanged fixed Spine reports; no ratios before six complete matrices |
| FullPR resident host | `/home/chuxiao/grasu-regraph-fullpr-comparison`, commit `1cc5ee5`; `gr-fullpr-preparation-v4` | Complete CPU preparation passes; hardware convergence remains unmeasured |
| FullPR hardware continuation | `gr-fullpr-board-continuation-v4` | Waiting for the exact new remote FullPR return; no board requested |
| Actual R / current K4 control | [Current-candidate audit, preflight and board binding](../../../original_regraph/k4_control/CURRENT_CANDIDATE.md) | Fresh six-input arithmetic audit and 24-row host preflight pass; exact new FullPR return remains pending |
| Same-input original/production G control | [Current-candidate preflight and board binding](../../../original_grasu/matched_production/CURRENT_CANDIDATE.md) | Fresh 22-step host preflight passes; independent eight-case, three-repeat board matrix waits for the exact new SSSP qualifier |
| Final figures | None from this candidate | Do not overwrite the frozen Fig. 7--11 handoff |

All three algorithm compile reports end in
`COMPILATION_PASS_AWAITING_RESOURCE_RTL_AND_ROUTE`. The three completed fresh
adapter reports end in
`FRESH_ADAPTER_AXI_RTL_PASS_NOT_ALGORITHM_RTL_OR_BOARD`. Their benches use
actual exported RTL and test backpressure, 1/64/128-cycle response latency,
local/global destination boundaries and AXI/stream conservation. They do not
measure full-system FPGA cycles.

## Fixed Sources And Runners

The numerical integration revision is
`87a0a2cdb8c647247bb4d61dbd06ca4e98028f0b`. The portable source closure
`production-algorithm-sources-v4` has 180 files and index SHA-256
`f92aa72f426f8c2177608fdb205af7aca0e14ef8dbe78e200fd69e4a1b70ea02`.
It includes the PR Apply packing fix and registered sixteen-lane G cache
comparison, without changing capacities or update semantics.

The FullPR host branch is based on integration `b06b07c` with the existing
host-only convergence change replayed as `1cc5ee5`. Its `kernels/` and
`include/` must remain identical to the routed numerical revision, except
`README.md` evidence checkpoints, which do not enter synthesis. Source,
headers, configuration and provenance remain checked; real-Git regression
tests reject changes to each. The earlier
`6eb197a` host preparation cannot silently stand in for this new source check.

| Runner/archive under LROOT | SHA-256 | Purpose |
| --- | --- | --- |
| `algorithm-return-runner-2b9cf3c.tar.gz` | `a1517443ce25b60df47aa219116dd84d994ba3344944ca1fffc49a4f6e2dace4` | Fresh compilation and local link continuation |
| `algorithm-local-return-runner-0b6f998.tar.gz` | `caeb563c03ffc14d9211c8436529f55404ec99ed28d556321c14b9dd19286532` | Strict local returns and remote SSSP qualification |
| `algorithm-fresh-rtl-runner-0b6f998.tar.gz` | `34701fa22b17c0ab33b5af2046df4d65d765d683e3f7800ee1c24b44ed09aa0c` | Fresh adapter benches, including `cpp/tests/routed_regraph/` |
| `current-board-runner-b0aa357.tar.gz` | `087cad9ececb3ce1359fbed3e5c59439ce70c3af16e16c11531a07230ac38a1f` | Three-algorithm continuation using the exact request file and either verified return transport |
| `fullpr-preparation-runner-dfdc287.tar.gz` | `2018780011364f5744a028a846dbc79ab7cf8e836b1c148f20a9085bad652e0a` | FullPR CPU preparation and exact-return board continuation |
| `original-r-k4-current-runner-v3.tar` | `7b590d1be2b201ed0e4b0e583b22d1749d3062408d46f2a94c873d2c1a4badc9` | Current-source R arithmetic/preflight, G preflight and independently qualified G/K4 board continuations |
| `high-memory-algorithm-runner-01e34c0.tar.gz` | `99f276f0e42674fd90094771162a4ad38ab4ce45981aea4831ce06abb8b81b3e` | Remote PR compilation, route and return, plus current local board continuations; independently hash-checked on both hosts |
| `resident-board-memory-runner-v1.tar.gz` | `4d24fd3101fecaec96e1b8568b975d802047b841495e17cc0830e45577249ebe` | Explicit 40/36-GiB fullgraph host budget and throttle-free paired timing admission; unchanged HLS artifacts |

Never modify a live runner or transplant a new result into an old attempt.

The paired request file deliberately points at `fullgraph-board-continuation-v13`,
not an earlier producer. Its G+R admissions must equal `fullgraph_requests.json`
algorithm by algorithm. The fixed Spine SSSP/CC/ResPR v2 reports and shared v1
artifact freeze remain unchanged. A regression test checks this wiring without
requiring hardware files; actual replay still checks every input, artifact,
raw log, timing boundary and the exact producer invocation. See the
[paired-replay guide](../../../fullgraph_readiness/paired_board/README.md).

## Exact Services

Each row names a distinct service and invocation; successful exit alone is
not timing, board or publication acceptance. Output names are relative to
LROOT unless explicitly remote.

| Output | Service | Invocation |
| --- | --- | --- |
| `g-cache-comparison-remote-follow-v2` | `spine-g-compare-remote-follow-20261019-v2.service` | `48c27c87776f41adae5016d3edc41c0d` |
| RROOT `g-cache-comparison-route-v2` | `spine-g-compare-route-remote-20261019-v2.service` | `bea6bfca3ec64eebac500cb7d55a73cf` |
| `production-cc-compile-route-local-v1` | `spine-production-cc-compile-route-local-20261018-v1.service` | `8866c7c03edc446a9dd2d14bdc39d876` |
| `production-cc-local-return-v1` | `spine-production-cc-local-return-20261018-v1.service` | `d3e68ffd064a43ae87b884a0eedfbb21` |
| RROOT `production-respr-compile-v3` | `spine-production-respr-compile-remote-20261019-v3.service` | `39a9f0694d9a43b3abd9b1c63c9c6352` |
| RROOT `production-fullpr-compile-v3` | `spine-production-fullpr-compile-remote-20261019-v3.service` | `dab5b719826a4780a227299f698cdd42` |
| RROOT `production-respr-compile-route-v3` | `spine-production-respr-compile-route-remote-20261019-v3.service` | `0e21f18dfec04551a895beeafb63869e` |
| RROOT `production-fullpr-compile-route-v3` | `spine-production-fullpr-compile-route-remote-20261019-v3.service` | `9ed927261b5448af9a64250a709fe161` |
| `production-respr-remote-return-v3` | `spine-production-respr-remote-return-20261019-v3.service` | `422d8b2cfb3540a9bbf123a00c92c52e` |
| `production-fullpr-remote-return-v3` | `spine-production-fullpr-remote-return-20261019-v3.service` | `c5a26cd5c40449198ce8af66dacaeef8` |
| `production-cc-fresh-adapter-rtl-v1` | `spine-production-cc-fresh-adapter-rtl-20261018-v1.service` | `be4097d72ff24021b4492c1ef750cb74` |
| `production-respr-fresh-adapter-rtl-v1` | `spine-production-respr-fresh-adapter-rtl-20261018-v1.service` | `e8655fb626564c3bbaf476b794778a1f` |
| `production-fullpr-fresh-adapter-rtl-v1` | `spine-production-fullpr-fresh-adapter-rtl-20261018-v1.service` | `a4f7df56d3a84788960635969d0378ff` |
| `fullgraph-board-continuation-v13` | `spine-fullgraph-board-continuation-20261019-v13.service` | `c7ddbf68cfcb4489a8627c4c7a333027` |
| `paired-board-continuation-v9` | `spine-paired-board-continuation-20261019-v9.service` | `9ff1b9972593446a9423b0881236483c` |
| `gr-fullpr-preparation-v4` | `spine-gr-fullpr-preparation-20261018-v4.service` | `5654d35624ac4a8490430ac24a54ec97` |
| `gr-fullpr-board-continuation-v4` | `spine-fullpr-board-continuation-20261019-v4.service` | `a9901a9de6224d008213f6335eca1bb3` |
| `original-r-k4-current-arithmetic-v2` | `spine-original-r-k4-current-arithmetic-20261019-v2.service` | `85a0a771aa564c04a066f5173bc07f7f` |
| `original-r-k4-current-host-preflight-v3` | `spine-original-r-k4-current-host-preflight-20261019-v3.service` | `900b130368d3475794828e42943ef8b3` |
| `original-r-k4-current-board-supervisor-v3` | `spine-original-r-k4-current-board-supervisor-20261019-v3.service` | `8e5b4ef8116e4e739591ac7467d9cacd` |
| `matched-g-current-host-preflight-v3` | `spine-matched-g-current-host-preflight-20261019-v3.service` | `173b52a20a0c4150958b49d7877cb8da` |
| `matched-g-current-board-follow-v5` | `spine-matched-g-current-board-follow-20261019-v5.service` | `a2a7ea1e1a264f0b9d7f043dc04f9b1f` |
| RROOT `original-g-external-port-route-v6` | `spine-original-g-external-port-route-20261019-v6.service` | `27f4b7a273d64392897cb4ff29396ef7` |
| `original-g-external-port-return-follow-v7` | `spine-original-g-external-port-return-20261019-v7.service` | `2a5bb99a6b0343689628d75558e61f33` |

## Admission And Memory

Local and remote returned artifacts take the same downstream gates: exact
successful producer invocation, requested algorithm, admission-report hash,
source closure, 150/450-MHz clocks, complete topology, and setup/hold/pulse
timing. The local return status is
`ALGORITHM_LOCAL_RETURN_ADMITTED_NOT_BOARD_OR_PUBLICATION`; this does not
authorize hardware by itself. SSSP additionally requires successful G native,
metadata-refresh and continuous-handoff board qualification.

The full-graph continuation accepts either verified return transport. Mocked
tests reject wrong algorithms, admission hashes, failed timing, error-bearing
reports and changed producer invocations. Actual board preparation replays
the offline host evidence and strict binary/timing pins again. FullPR uses
its distinct resident-convergence protocol, not a three-sweep substitute.

Default builds retain finite cgroups, zero swap, full peer budgets and a
32+8-GiB reserve; unknown peers still block. The explicit
`seele-reserve-128g-v1` profile is restricted to the 499-GiB remote host:
40/36-GiB max/high per owned build, zero swap, full bounded-peer budgets and a
128+8-GiB reserve. Observed unbounded foreign compilers are disclosed, never
modified; the live watchdog stops only our own tree if the reserve is lost.
See the [algorithm build policy](../algorithm_build/README.md#remote-memory-profile).

The earlier SSSP v1 failed because live legacy helper changes violated its
frozen parent pins. The helper bytes were restored, and v2 uses an independent
immutable runner; v1's failure remains intact. Matched-G v4 was launched with
8 GiB where that supervisor requires at most 4 GiB and failed before board
access; v5 has the required 4/3-GiB containment. Neither failure is an algorithm
performance result. The e22b48e runner archive SHA-256 is
`b1925944fce220190f5fb7dde8cc75ccd576ee50f31ff6fffeceb5639577840e`.

The latest FullPR CPU preparation uses the separate clean host worktree
`1cc5ee5`. Its earlier `gr-fullpr-preparation-v3` was operator-cancelled while
waiting for a 24-GiB budget, before any child step. Its retained
`FAILED_RETAINED`/`KeyboardInterrupt` record is not a numerical failure.
The replacement v4 uses the exact 4-GiB complete scope and 32-GiB reserve,
without dropping a case or CPU-reference check. It completes compilation,
the smoke and all AU/SU/WK preparations with no errors or memory-limit/OOM
events. The service's recorded memory peak is 825,479,168 bytes. Independent
raw-log and source/input-pin replay passes. Its `results.json` SHA-256 is
`34611b0194a5989d19df5f2e24d4b4b79bab90ed5498508c51d47f2ca811de8d`.

FullPR board continuation v4 pins that exact preparation hash and remote
return producer `spine-production-fullpr-remote-return-20261019-v3.service`,
invocation `c5a26cd5c40449198ce8af66dacaeef8`. It is waiting, with
`board_requested=false`, not a successful hardware result. Routing's 40-GiB
and board execution's 24-GiB limits are unchanged.

The CC link's own service originally inherited a single CPU despite its
eight-CPU quota. The separate immutable addendum
`production-cc-affinity-adjustment-v1/{request,results}.json` records changing
only that invocation's live threads to CPUs 96--101, 106 and 107. All live
threads were checked; source, link options, 40-GiB limit and zero swap remain
unchanged. This is build-host scheduling evidence, not an FPGA performance
measurement, and does not modify the frozen runner or earlier records.

The earlier, local ResPR/FullPR link supervisors received the same kind
of correction before starting children. The separate
`production-pending-route-affinity-adjustment-v1/{request,results}.json`
pins their exact invocations and verifies every live thread: ResPR uses
CPUs 108--115 and FullPR uses 16--23, instead of CPUs 121 and 122 respectively.
Their eight-CPU quotas, 40/36-GiB hard/high memory limits, zero swap and
memory-admission rules are unchanged. This does not admit either route or
modify a frozen runner, source or link option.

## Remote PR Migration

The fresh remote PR chains use the unchanged v4 source closure and immutable
`01e34c0` runner. Each compilation and route follower has a 40/36-GiB
hard/high limit, zero swap and an eight-CPU quota with matching affinity:
ResPR uses CPUs 32--39, FullPR 40--47. They explicitly record the
`seele-reserve-128g-v1` profile. Local return followers verify the exact remote
compile-to-route invocation and retain sealed receipts before admission.
Neither an early compile pass nor a returned file alone authorizes board use.

The frozen request copies are `fullgraph-board-requests-v13.json` and
`paired-board-requests-v9.json` under LROOT. They preserve the SSSP and CC
bindings and fixed Spine reports, changing only the ResPR return and exact
producer identity. FullPR and the independent R/K4 supervisor likewise bind
the new FullPR return, without changing algorithm or timing semantics.

Before migration, exact-invocation checks found the local ResPR/FullPR link
followers waiting for memory without a vendor link child. Fullgraph v10,
paired v6, FullPR v3 and R/K4 v2 were also waiting, without board requests.
Only those obsolete waiting tasks were interrupted. Their original
`FAILED_RETAINED` / `KeyboardInterrupt` reports and completed local XOs stay
intact; these cancellations are not numerical, route-timing or board failures.
The old local PR return followers consequently retain
`required route terminated unsuccessfully; no board execution`; neither
requested a board. Their replacement remote followers do not reuse those
reports or count them as successful returns.
An exited service may report success while its retained experiment reports
cancellation: always inspect the experiment report. New downstream services
use new output paths and the exact identities listed above.

One additional remote FullPR build was explicitly cancelled after verifying
that it used obsolete numerical revision `1a5650c79ae0c29418b93184a1590f256e33f0b6`,
not the current v4 closure. Its exact unit was
`spine-production-fullpr-compile-route-20261018-v1.service`, invocation
`6bc5f930f57f47dc994bdcf21cea3635`, output
`production-fullpr-compile-route-follow-v1/`. The separate remote
`obsolete-fullpr-v3-route-cancellation-v1/` addendum records the source and
downstream-dependency checks and operator interruption. Raw logs remain
intact. This is a superseded-source cancellation, not a numerical or timing
failure; current FullPR v3 continues under the exact service listed above.

## CC Return And Board Affinity

The new CC bitstream SHA-256 is
`f0328d37dd986c82bc30f6fcd1b4ae7a97522d14583170cb26489c02bf4b4681`.
Strict return checks admit its exact v4 sources, 22 kernel instances, 731
memory argument bindings and 31 stream pairs. Post-route WNS is 0.003 ns,
WHS 0.009 ns and WPWS 0.000 ns, with zero failing setup/hold/pulse slack.
The admitted return is not an FPGA correctness or performance result.

Fullgraph v11 reached the CC preparation but failed the two-CPU-affinity
gate before requesting a card. Its process saw all 128 CPUs even though the
unit declared `AllowedCPUs=118-119`. The failed report and paired v7's
corresponding rejection remain intact. Fullgraph v12 and paired v8 use the
same immutable runner, artifacts, requests and boundary, with explicit
`taskset -c 118,119`; no HLS or timer was changed. The paired request paths
change only to the new producer. Actual child affinity is checked again by
the existing board-study gate before any FPGA execution.

`waiting-board-affinity-adjustment-v1/{request,results}.json` records an
equivalent correction for the three still-waiting, exact-invocation FullPR,
matched-G and R/K4 supervisors. Only their own live threads were changed to
their already declared CPU pairs. The source, runtime, memory containment,
board selection and timing boundaries were unchanged; no performance
measurement existed in those waiting services when the correction occurred.

## Board Host Memory And Timing Admission

Fullgraph v12 passed the CC smoke and first AU/SU/WK/SO/PK repetitions, then
its LJ host preparation was persistently throttled by the 22-GiB soft limit.
The saved request observes `mem_cgroup_handle_over_high`, not an FPGA
correctness error. The exact invocation was interrupted; the child was
cleaned up and its complete raw record retained. Final events are
`high=55157`, `max=oom=oom_kill=oom_group_kill=0`. Neither the partial matrix
nor paired v8 is timing-admitted. See LROOT
`cc-host-memory-restart-v1/` and `board-memory-policy-pre-edit-v1/`.

The new immutable runner exposes only two finite resident-board budgets:
the unchanged 24/22-GiB default and explicit 40/36-GiB fullgraph execution.
V13 uses the latter with zero swap, group OOM kill, full bounded-peer
reservations, the same 32-GiB system reserve, explicit CPUs 118--119 and
unchanged algorithms, inputs, xclbins and wall boundary. At launch all
memory events are zero. Each completed child and the terminal report must
have zero `high`, `max` and OOM events. Paired replay checks the declared
budget against containment and each raw resource record; missing events or
unrecorded budget changes cannot pass. Any new throttling stops acceptance.

The existing fixed-Spine reports retain their 24/22-GiB limits and all have
zero `high`/limit/OOM events. Unequal inactive host safety caps do not change
the device resources; neither arm may be throttled for timing acceptance.
V13 and paired v9 restart into new paths, not overwritten v12/v8 reports.
Their runner archive has 2321 hash-verified files; its source/diff identities
are recorded in LROOT `resident-board-memory-runner-v1.manifest.json`.

## Simulator Timing Boundary

Do not call the newest complete G calibrated from component checks alone.
The current finite cache model declares bank interval 3 cycles and latency
7 cycles in `cpp/include/spine_sim/grasu_update/cached_processor.hpp`.
The new registered cache's HLS `lane_update` report observes loop II=3 and
pipeline depth 5, although the source requests II=1. The matching II is a
component schedule check; depth 5 is not the model's complete packet latency
boundary and must not be substituted for 7 without a separate transaction
comparison. Neither HLS depth nor the earlier isolated cache RTL establishes
the complete routed G's cycles, host time or publication-level performance.
The new G hardware qualifier and matched original-G matrix remain necessary.

## Remaining Work

1. Admit actual new routes; retain negative timing and metadata failures.
2. Complete G/metadata/continuous-handoff correctness on the new artifact,
   and all declared algorithm hardware smokes and convergence matrices.
3. Separately compare original G, original R, matched A4 and actual adapter/K4;
   do not infer each component from an end-to-end speedup.
4. Pair against fixed Spine under the same resident old-converged-to-final-
   readback boundary, including host relaunch. FullPR's failed Spine arm
   cannot supply a paired speedup without a separately verified fix.
5. Validate the corresponding simulator identities, then package new
   Fig. 7--11 data, code, previews and limitations in the simulator repository.
   Do not edit the paper or relabel model predictions as board measurements.
