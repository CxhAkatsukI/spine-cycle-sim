# Bounded GraSU Cache And Revised FPGA Matrix

## What Is Being Delivered

The requested follow-up is an actual SSSP/CC/ResPR G+R versus Spine FPGA
comparison, not another predicted replacement for hardware data. The ReGraph
publication-scale gap (approximately 2.47 times on the recorded Amazon
control) remains disclosed and is not a blocker for this study. No artificial
timing coefficient is introduced to remove it.

| Evidence | Checkpoint status |
| --- | --- |
| Bounded-cache source oracle and token/plain functional checks | Passed |
| Fresh HLS exports and exact comparison against old exported ABI | Passed |
| Three native G+R hosts | Built, backward-compatible argument selection |
| Cached processor, cycle engine, short-layout G runtime regressions | Passed |
| Fresh Release core build and complete CTest suite | 31 of 31 passed |
| Revised G+R SSSP, CC, ResPR hardware | Queued under memory admission |
| Sparse-apply Spine ResPR hardware | Compiling |
| New-kernel FPGA comparisons | 0 of 24 pairs; pending hardware |
| Production SST bounded-cache option and numerical calibration | Not promoted or rerun |

Queued, exported and routed are separate gates. The live result files below
are authoritative after this checkpoint. Existing figure data and the paper
are not changed by this study.

## Diagnosed Costs And Source Changes

Two observed costs have different ownership:

1. Previously nonresident graph/update/metadata buffers could migrate inside
   a later kernel launch. The shared host helper explicitly establishes their
   initial residency before updates. Initial migration is timed separately;
   it is not removed from a whole-startup accounting claim.
2. The GraSU URAM cache previously preloaded and wrote back all 131072 words
   per invocation, even when the shard's PMA half contained far fewer words.
   A final `valid_segments` scalar bounds those transfers, rounded up to
   sixteen banks. Physical cache capacity, registered update logic, transfer
   II, sharding and ReGraph are unchanged. No cache contents are assumed
   persistent across invocations; every required valid word is transferred.

The HLS source and experiment runners belong to the integration repository:
`docs/sharded_k4_cache_extent/README.md` and `validation/cache_extent/`.
SSSP/CC add argument 3; PageRank adds argument 2. Old kernels retain their old
ABI. A new experiment may not silently substitute an old kernel when a new
build is missing.

This simulator adds the explicit, default-off `compact_cache_valid_extent`
option for the full-capacity cached processor configuration. Default behavior
still transfers the full cache. The core derives each half's span from the
actual PMA layout, models all rounded reads/writes and completion, rejects
out-of-span updates, and preserves untouched words. The component checks
exercise empty and boundary spans, finite queues, degree backpressure, RAW
hazards, acknowledged writes and both registration orders. Ten short-layout
runtime cases additionally compare the final graph to an independent oracle
and check the complete transfer ledger.

The production SST plugin does not yet expose this opt-in configuration.
Passing these core checks is neither a refreshed production-plugin result nor
new FPGA calibration. Timing differences caused by real HBM, host scheduling
and physical routing remain empirical questions for the new board matrix.

## Portable Component Prediction

[`component_prediction.csv`](component_prediction.csv) is a focused cache
diagnostic, not total G+R runtime. It contains 257 alternating edits to one
row, immediate producer completion, one 64-byte AXI port, finite depth-one
queues, two outstanding requests and the fixed mock-memory configuration
`{1,16,1,16,64,true}` at a 200-MHz component clock. The real matrix requests
150 MHz and records actual routed clocks. `degree=1` includes publication
consumed once every five cycles. Both registration orders produce identical
cycles and all final state/traffic checks pass.

At extent 1, sixteen words are transferred each way; at full extent, 131072
words are transferred. The corresponding no-degree predictions are 883 and
527837 cycles. These numbers demonstrate the intended bounded-transfer
mechanism under stated assumptions. They are not measurements of the FPGA,
a whole-system speedup, or evidence of equal simulator/HLS timing.

```bash
cmake -S . -B /path/to/fresh-build -DCMAKE_BUILD_TYPE=Release
cmake --build /path/to/fresh-build --target grasu_cached_processor_tests grasu_runtime_tests -j1
/path/to/fresh-build/cpp/grasu_cached_processor_tests
/path/to/fresh-build/cpp/grasu_cached_processor_tests --extent-benchmark
/path/to/fresh-build/cpp/grasu_runtime_tests
ctest --test-dir /path/to/fresh-build --output-on-failure --timeout 180 -j1
```

The full regression completed in 109.46 seconds, with a 94.4-MiB service
memory peak, in a 2-GiB hard/1.5-GiB high/zero-swap group. The saved detailed
log is `sim-after/Testing/Temporary/LastTest.log` under the live root below.
This suite covers both original baselines, the integrated ReGraph path,
Spine core/owner/lifecycle behavior, AXI and GraSU. Integration-side checks
also passed: 41 complete-G validation tests, eight cache-study tests and
four resident-log comparison tests. The HLS-side source/runner checkpoint
is commit `9f6d1a6` in `grasu-regraph-integration`.

No fresh SST-plugin timing or FPGA calibration was run for this opt-in
simulator path. The default production plugin is unchanged. Core regression,
HLS synthesis and future routed measurements are distinct evidence gates.

## Frozen Hardware Matrix

Twenty-four pairs cover SSSP, CC and ResPR on AU, SU, WK, SO, PK, LJ, LJ08
and R19. Each starts from the same old converged state, applies the same eight
logical updates, and runs until the new result converges. Reciprocal physical
CC updates are not counted as extra logical updates. ResPR uses the shared
fixed threshold `1e-6`, not threshold divided by vertex count.

The resident wall-time interval includes update processing, adapter/R
propagation, host launch/wait, inter-round relaunch and final readback.
Initial graph/PMA creation and residency, old-state loading, batch preparation
and upload, and CPU oracles are outside both systems' resident interval and
retained separately. This is not whole-startup setup-inclusive latency.
Spine remains host-orchestrated, not an autonomous persistent device.

Each algorithm must pass AU before the remaining seven cases. One warmup
and three measured pairs alternate order. Old/new convergence, all required
correctness checks and zero mismatches are mandatory. Actual routed data
clocks are reported even if below 150 MHz. G+R native hosts use GCC 15.2
`-O2`; the current Spine resident hosts use GCC 15.2 `-O3`.

## Evidence And Safety

Live root: `/data/chuxiao/builds/grasu-cache-extent-20261025`.

| Path under the root | Meaning |
| --- | --- |
| `source-v1/results.json` | Frozen executable source checks |
| `hls-v1/results.json` | Both HLS exports; no routed timing claim |
| `route-v2/{sssp,cc,respr}/{manifest,results}.json` | New bounded-cache links and ABI review |
| `spine-respr-v2/` | Fresh sparse-apply Spine ResPR source and build provenance |
| `matrix-inputs-v3/plan.json` | Frozen graph, host, source, tool and binary identities |
| `matrix-v2/{results.json,summary.csv}` | All 24 cases, including missing/failed rows |
| `sim-before/`, `sim-after/` | Separate Release component builds |
| `sim-extent-benchmark-v1.csv` | Original portable component diagnostic |
| `host-control-au-v1/results.json` | OLD G+R kernel with the revised host |

The old-kernel AU control passes correctness with G+R 21.889057 ms and Spine
4.497250 ms median resident wall time (4.867209 times). It proves this control
runs correctly; it is not a new bounded-kernel measurement, an all-graph
result, or an isolated causal estimate of the host optimization.

Compiler trees are capped at 56 GiB (52-GiB high watermark), zero swap and
whole-group OOM termination. Admission keeps 24 GiB available and accounts
for unused peer reservations. Historical complete G+R tree peaks were around
41--45 GiB. Concurrent compilers are admitted only if that total budget fits.
Board hosts have finite 16--32-GiB groups and share an exclusive board lock.
Interrupted `v1` runs and their logs are retained, not relabeled as passes.

No large bitstream or raw compiler log is checked into this repository.
The integration guide owns runner commands; immutable manifests above retain
the exact arguments and source hashes. This guide and the portable CSV are
the reviewable simulator-side entry point, not a substitute for pending board
evidence.
