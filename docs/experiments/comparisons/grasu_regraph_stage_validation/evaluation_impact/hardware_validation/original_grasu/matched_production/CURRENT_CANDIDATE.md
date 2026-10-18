# Current Same-Input G Candidate

## Scope

This is the current production-G counterpart to the unchanged original-G
eight-input control. It is not a board-performance acceptance. Local output
names below are under
`/data/chuxiao/experiments/baseline_hardware_validation_20261015` (LROOT).
The [control guide](README.md) defines the logical-state, timing and physical
representation differences; its earlier runs remain historical evidence.

## Completed Host Prerequisite

`matched-g-current-host-preflight-v3/results.json` reports
`MATCHED_G_HOST_PREFLIGHT_PASS_NOT_BOARD_OR_PERFORMANCE`, with no errors.
Its SHA-256 is
`e5406aa696e07c38a91d468354ca28ca782ee942ed02b543055f20375aa61dd2`.
All 22 steps pass: Release and UBSan compilation, runtime-loader inspection,
all eight original inputs under each build, two malformed-header checks and
rejection of unleased board access. No FPGA is enumerated or programmed.

The service is `spine-matched-g-current-host-preflight-20261019-v3.service`,
invocation `173b52a20a0c4150958b49d7877cb8da`. It exits zero after 27.6 seconds
including admission, with a recorded cgroup peak of 363,253,760 bytes. This
is CPU validation time, not hardware latency. The separate immutable
`matched-g-current-host-preflight-v3.admission.json` records atomic admission
of the full 4-GiB scope, the concurrent CC route's full 40-GiB budget and a
32-GiB reserve. Hard/high limits are 4 GiB / 3584 MiB, with zero swap, group
OOM kill, CPU 122, 100% CPU quota and a 2400-second service lifetime.

The source is integration `b06b07c3bcd2b303fcb87bf33b5db11addd42a80`.
Both the preflight and the board waiter use immutable simulator runner
`original-r-k4-current-runner-v3`, exported from `02281f9`; the shared archive
`original-r-k4-current-runner-v3.tar` has SHA-256
`7b590d1be2b201ed0e4b0e583b22d1749d3062408d46f2a94c873d2c1a4badc9`.
The directory name does not restrict its included G modules. Do not modify
the snapshot or completed reports.

The original prerequisite remains `original-g-board-host-preflight-v4`,
SHA-256 `c5fcccaf865c8d50cc5b0f74f4ea2dda53359a125fc927ae217915287c9d1ef6`.
Supplying either digest never disables input, source or runtime-pin replay.

## Exact Board Continuation

| Binding | Exact value |
| --- | --- |
| Output | `matched-g-current-board-follow-v3` |
| Service | `spine-matched-g-current-board-follow-20261019-v3.service` |
| Invocation | `cfe24d2f51ad40bca5075d9a1309ffb9` |
| Host prerequisite | `matched-g-current-host-preflight-v3` |
| Required qualifier output | `g-cache-comparison-remote-follow-v1` |
| Required qualifier service | `spine-g-compare-remote-follow-20261018-v1.service` |
| Required qualifier invocation | `e25239587873400c86c43d99d72417a2` |
| Parent manifest | `g-cache-comparison-route-v2/manifest.json` |
| Board | Device 0, exclusive BDF lease before programming |

At deployment, the waiter is `WAITING_FOR_EXACT_PRODUCTION_QUALIFIER`, with
no board launch. It retains 4/3-GiB hard/high limits, zero swap, group OOM
kill, CPU 122, 100% quota and a 140000-second lifetime. After the exact
successful qualifier, strict source/topology/clock/timing admission and
full-budget memory admission must pass again. All eight inputs then run
three times, preserving raw events, complete state and guards.

The old `matched-g-production-board-follow-v2` failed on its old required
route before any board execution. It is not rebound to the new qualifier.
Neither a waiting continuation nor a host pass establishes a G speed match,
original-publication reproduction, or a finalized figure.
