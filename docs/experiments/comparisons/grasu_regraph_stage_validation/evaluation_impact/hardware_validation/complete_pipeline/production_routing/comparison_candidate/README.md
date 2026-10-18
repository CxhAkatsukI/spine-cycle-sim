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
| Fresh CC, ResPR and FullPR compilation | `production-cc-compile-local-v2`, `production-respr-compile-local-v2`, `production-fullpr-compile-local-v1` | All compile; not routed timing or device correctness |
| Fresh CC and ResPR adapter RTL | `production-{cc,respr}-fresh-adapter-rtl-v1` | Both pass; not complete-algorithm RTL or board performance |
| Fresh FullPR adapter RTL | `production-fullpr-fresh-adapter-rtl-v1` | Passes separately; not complete-algorithm RTL or board performance |
| New SSSP link and qualification | RROOT `g-cache-comparison-route-v1`; LROOT `g-cache-comparison-remote-follow-v1` | Pending exact route and strict admission |
| New CC/ResPR/FullPR links | `production-{cc,respr,fullpr}-compile-route-local-v1` | Independent bounded attempts; inspect live state, not this table |
| Full-graph new-G+R performance | [Exact request file](fullgraph_requests.json) | Not yet accepted; requires successful returns and board runs |
| FullPR resident host | `/home/chuxiao/grasu-regraph-fullpr-comparison`, commit `1cc5ee5` | Host-only convergence port onto latest kernels; CPU preparation and board validation remain separate |
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

Never modify a live runner or transplant a new result into an old attempt.

## Exact Services

Each row names a distinct service and invocation; successful exit alone is
not timing, board or publication acceptance. Output names are relative to
LROOT unless explicitly remote.

| Output | Service | Invocation |
| --- | --- | --- |
| `g-cache-comparison-remote-follow-v1` | `spine-g-compare-remote-follow-20261018-v1.service` | `e25239587873400c86c43d99d72417a2` |
| RROOT `g-cache-comparison-route-v1` | `spine-g-compare-route-remote-20261018-v1.service` | `6a4d97de1f854fbf8e41d6930fab0d51` |
| `production-cc-compile-route-local-v1` | `spine-production-cc-compile-route-local-20261018-v1.service` | `8866c7c03edc446a9dd2d14bdc39d876` |
| `production-respr-compile-route-local-v1` | `spine-production-respr-compile-route-local-20261018-v1.service` | `37e683aed86d4459932d9ad4c88935aa` |
| `production-fullpr-compile-route-local-v1` | `spine-production-fullpr-compile-route-local-20261018-v1.service` | `0bba11cc2a3e4d7d9ec7d6e88536616a` |
| `production-cc-local-return-v1` | `spine-production-cc-local-return-20261018-v1.service` | `d3e68ffd064a43ae87b884a0eedfbb21` |
| `production-respr-local-return-v1` | `spine-production-respr-local-return-20261018-v1.service` | `fc6b42253a824b96b03e4ae9a0a5b53a` |
| `production-fullpr-local-return-v1` | `spine-production-fullpr-local-return-20261018-v1.service` | `1ee16f77eea84bbba4ac305ad8ae449c` |
| `production-cc-fresh-adapter-rtl-v1` | `spine-production-cc-fresh-adapter-rtl-20261018-v1.service` | `be4097d72ff24021b4492c1ef750cb74` |
| `production-respr-fresh-adapter-rtl-v1` | `spine-production-respr-fresh-adapter-rtl-20261018-v1.service` | `e8655fb626564c3bbaf476b794778a1f` |
| `production-fullpr-fresh-adapter-rtl-v1` | `spine-production-fullpr-fresh-adapter-rtl-20261018-v1.service` | `a4f7df56d3a84788960635969d0378ff` |
| `fullgraph-board-continuation-v9` | `spine-fullgraph-board-continuation-20261018-v9.service` | `e612a14bee3b4681ab4a17b795f6c7b0` |

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

Builds use finite cgroups, zero swap and atomic admission using full peer
budgets plus 32+8 GiB reserve. Route limits are 40/36 GiB max/high; adapter RTL
limits are 4/3 GiB. Other bounded tools need not exit if budgets fit. An
unbounded foreign Vivado in `session-32960.scope` was observed on the remote
host; spare RAM alone does not authorize starting beside that unknown budget.
Do not stop or cap someone else's job without permission. Live JSON and
cgroup records decide whether this condition still exists.

The latest FullPR CPU preparation uses the separate clean host worktree
`1cc5ee5`; its earlier `gr-fullpr-preparation-v3` waits for a 24-GiB budget.
The bounded-cohort executor also supports an exact 4-GiB complete scope,
based on the earlier cohort's 825,266,176-byte peak, without dropping any
case or CPU-reference check. This does not reduce routing's 40-GiB limit,
board execution's 24-GiB limit or the CPU preparation's 32-GiB reserve.
Any superseding attempt gets a new output and service; the waiting record
is retained, not overwritten or presented as a completed preparation.

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
