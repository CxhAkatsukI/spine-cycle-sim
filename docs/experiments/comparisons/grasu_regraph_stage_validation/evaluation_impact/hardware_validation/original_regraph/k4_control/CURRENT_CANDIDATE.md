# Current Adapter/K4 Candidate

## Scope

This page binds the independent R control to the current production source
closure. It supersedes only the candidate wiring, not the retained historical
runs in the [control guide](README.md). It is not a board-performance result.
All local paths below are under
`/data/chuxiao/experiments/baseline_hardware_validation_20261015` (LROOT).

The unchanged original A4 CSR, tasks, numeric input contributions and two
divisor bindings feed the production destination-sharded PMA and 23-channel
K4 path. The control is one static FullPR superstep, damping 108/128, initially
zero rank and zero base/dangling share. It excludes G updates, preparation and
convergence. Fixed-point A4 and binary32 K4 have separate arithmetic oracles;
their output bits are not declared equal. Four frontends do not establish
equal channel resources or isolated adapter overhead.

## Completed Prerequisites

| Evidence | Result | Result SHA-256 |
| --- | --- | --- |
| `original-r-k4-current-arithmetic-v2/results.json` | Six frozen inputs audited; no errors | `0d25bb3b6b2218bbca0b6eec0a8c506c58f7f9ded587456761f078289d3d4065` |
| `original-r-k4-current-host-preflight-v3/results.json` | All 24 declared rows completed: 16 prepared passes, eight explicit duplicate-edge rejections; no errors | `5c2d63c2e9784210c694405ed77eb771df1658e3a355fd9f600185a30de8c047` |

The audit took 17.1 seconds, peaking at 203,567,104 bytes under a 2-GiB
hard / 1536-MiB high limit. The full Release/UBSan host preflight took 141.8
seconds, peaking at 1,520,766,976 bytes under a 4-GiB hard / 3584-MiB high
limit. Both use zero swap, group-OOM containment, CPU 123, 100% CPU quota and
data-disk temporary files; neither reports memory-limit/OOM events. These
wall times describe CPU validation, not FPGA latency.

Services and invocations:

- Audit: `spine-original-r-k4-current-arithmetic-20261019-v2.service`,
  `85a0a771aa564c04a066f5173bc07f7f`.
- Preflight: `spine-original-r-k4-current-host-preflight-20261019-v3.service`,
  `900b130368d3475794828e42943ef8b3`.

Both use immutable runner `original-r-k4-current-runner-v3`, from simulator
commit `02281f9`. Archive `original-r-k4-current-runner-v3.tar` has SHA-256
`7b590d1be2b201ed0e4b0e583b22d1749d3062408d46f2a94c873d2c1a4badc9`.
Do not edit that snapshot or overwrite its completed reports.

## Exact Board Continuation

The current continuation uses immutable runner
`high-memory-algorithm-runner-01e34c0`, without replacing the frozen preflight
or numerical source closure. Its archive SHA-256 is
`99f276f0e42674fd90094771162a4ad38ab4ce45981aea4831ce06abb8b81b3e`.
Output is `original-r-k4-current-board-supervisor-v3`:

| Binding | Exact value |
| --- | --- |
| Service | `spine-original-r-k4-current-board-supervisor-20261019-v3.service` |
| Invocation | `8e5b4ef8116e4e739591ac7467d9cacd` |
| Preflight | `original-r-k4-current-host-preflight-v3` |
| Source closure | `production-algorithm-sources-v4` |
| Required remote return | `production-fullpr-remote-return-v3` |
| Required producer | `spine-production-fullpr-remote-return-20261019-v3.service` |
| Required producer invocation | `c5a26cd5c40449198ce8af66dacaeef8` |
| Board | Device index 1, with an exclusive BDF lease before programming |

At deployment it is `WAITING_FOR_EXACT_ADMITTED_FULLPR_RETURN`, with no board
launch, programming or measured hardware timing. Inspect live `results.json`
and the exact invocation; this page is not a substitute for live evidence.
The supervisor keeps 8/7-GiB hard/high limits, zero swap, CPUs 124--125, 200%
CPU quota, a 146000-second service lifetime and a 133200-second maximum wait.
Full finite peer budgets plus 24-GiB reserve and 8-GiB background must fit
before its worker starts. Unknown/unbounded compiler peers prevent admission.

The plan preserves all 18 board rows: three graphs, two bindings and three
repetitions. Twelve are executable; six `boundary_ring` rows remain
unsupported because the frozen CSR contains 64 duplicate edges. They are
not deduplicated or replaced with passing cases. Actual execution still
requires strict FullPR source/ABI, 150/450-MHz clocks, global timing, complete
raw buffer/guard checks and independent timestamp replay.

Prepared revision `b06b07c3bcd2b303fcb87bf33b5db11addd42a80` and numerical
route revision `87a0a2cdb8c647247bb4d61dbd06ca4e98028f0b` are recorded
separately. The checked graph/runtime-plan/l2 headers and PR Apply source
are identical; Apply SHA-256 is
`91d9b7da78b08c4ce7bc49a7b72afed7421e9dd1e676bb9508aaac8775524ff2`.
This limited check is not a full revision-equivalence proof. Publication,
default-profile, same-resource and latest-revision-performance claims remain
false until their independent gates pass.

## Retained Older Failure

Supervisor v2 was operator-cancelled while
`WAITING_FOR_EXACT_ADMITTED_FULLPR_RETURN`, with no board launch, to switch
from the still-waiting local build to the new remote FullPR chain. Its exact
invocation was `05f1b2a02e3a451ba7b1d455777e9f7f`; its retained
`FAILED_RETAINED` / `KeyboardInterrupt` is not a measured performance failure.
No report or artifact was copied into the replacement v3 attempt.

The older remote `production-fullpr-route-v2` completed link, but its service
was not retained after exit. `production-fullpr-return-follow-v2` therefore
stopped with `route service disappeared or its invocation changed`, before
receipt sealing, strict timing review or any board request. The dependent
`original-r-k4-board-supervisor-v1` stopped without programming. This is a
service-provenance failure, not a measured algorithm or timing failure. Its
records remain unchanged. The current route/return services retain terminal
state; no old bitstream is promoted into this current-candidate control.
