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
| HLS exports and exact comparison against old exported ABI | Fresh `hls-zfs-v3` export passed; new link ABI review passed |
| Three native G+R hosts | Built, backward-compatible argument selection |
| Cached processor, cycle engine, short-layout G runtime regressions | Passed |
| Fresh Release core build and complete CTest suite | 31 of 31 passed |
| Revised G+R SSSP, CC, ResPR hardware | `route-zfs-v2`: SSSP and ResPR running; CC waiting for finite memory admission |
| Sparse-apply Spine ResPR hardware | Compiler succeeded; independent artifact audit passed; board correctness pending |
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
simulator path. The frozen production plugin is unchanged. Core regression,
HLS synthesis and future routed measurements are distinct evidence gates.

### Sharded Metadata Routing

The sharded runtime may place row metadata and binary-search heads in
different HBM channels. Parallel search previously rejected that layout,
even though its single metadata AXI master can route requests to either
channel. It now sets the binary request's existing `target_channel`; row
requests retain the master's default channel. This matches the HLS binding's
shared `gmem_binary` bundle without adding a master, bandwidth, outstanding
credits or a second metadata copy. The parallel configuration still has 18
masters; the legacy configuration has 22.

The AXI retry shortcut also now coalesces same-channel reservation stalls
only when no unissued burst overrides that master's fixed channel. Otherwise
it checks each eligible burst, so a blocked channel cannot hide work for
another channel. Default fixed-channel behavior remains unchanged. Controls
compare the same explicitly routed traffic with and without a fixed default,
including both component registration orders, exact cycle/stall equality,
per-channel read/write payloads and the one-beat-per-cycle physical budget.

The new sharded oracle uses five 64-vertex destination partitions with
1/31/33/1/0 PMA segments. Three touched partitions exercise odd/even half
sizes and sixteen-bank rounding; populated and empty untouched partitions
must remain intact. Both degree-disabled and degree-enabled runs check the
final graph, zero outstanding requests, all 96 cache words transferred each
way, and preservation of global degree state across shard transitions.
Parallel-search tests separately cover shared/separate metadata channels,
16/64 contexts, backpressure and registration-order equivalence.

These are core routing and correctness checks, not permission to substitute
new simulator predictions for the pending FPGA matrix. No live build's
source or runner pin was changed by this simulator follow-up.

The fresh Release build in `sim-sharded-v1/` passes all 31 CTest executables
in 114.26 seconds (101.3-MiB service peak). `regression.xml` and
`Testing/Temporary/LastTest.log` retain individual results. Both this build
and the fresh SST library use the routing correction. The earlier compiler
attempt exposed a GCC 15 warning in the new test's temporary-region lookup;
the test now copies the returned region. No production lifetime bug was
inferred from that diagnostic.

The default SST plugin rebuild in `sst-sharded-v2/` also passes three online
memory probes (`sst-sharded-smoke-v1/`) and the 1600-byte payload round trip
(`sst-sharded-payload-v1/`, 95 cycles, 50 backend requests). These validate
backend/AXI/DRAM request conservation and payloads, not GraSU stage timing or
the opt-in bounded-cache mode. The plugin SHA-256 is
`0d7c24e5c13b8670f52bb3a4859163d5c186ee6ce7819772971083d45e128fa9`.
It uses the existing patched DRAMSim3 dependency
`/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729`; the first attempt
against an unpatched dependency failed on the required idle APIs. Both
failed attempts remain in their systemd journals. No frozen production
plugin, numerical calibration or figure data was replaced.

## Frozen Hardware Matrix

Twenty-four pairs cover SSSP, CC and ResPR on AU, SU, WK, SO, PK, LJ, LJ08
and R19. Each starts from the same old converged state, applies the same eight
logical updates, and runs until the new result converges. Reciprocal physical
CC updates are not counted as extra logical updates. ResPR uses the shared
fixed threshold `1e-6`, not threshold divided by vertex count.

### ResPR Input Preconditions

The eight frozen ResPR inputs were independently streamed on 2026-10-25.
The scan checked their declared record counts, ordered initial source IDs,
complete source coverage, and eight positive insertion records. Every initial
vertex has an outgoing edge; insertion cannot introduce a sink.

| Dataset | Vertices | Initial edges | Initial zero-outdegree vertices | Insertions |
| --- | ---: | ---: | ---: | ---: |
| AU | 515281 | 826848 | 0 | 8 |
| SU | 567316 | 1075035 | 0 | 8 |
| WK | 1140149 | 2190639 | 0 | 8 |
| SO | 6024271 | 28299669 | 0 | 8 |
| PK | 1632803 | 44603928 | 0 | 8 |
| LJ | 4847571 | 85703436 | 0 | 8 |
| LJ08 | 5363260 | 99028616 | 0 | 8 |
| R19 | 524288 | 15672181 | 0 | 8 |

This matters because the G+R oracle supports dangling-mass redistribution,
whereas the Spine resident propagation reference uses sink-free semantics.
For these particular old and updated snapshots the dangling contribution is
zero. This check does not establish equivalence on graphs containing sinks,
nor replace the final-state correctness checks on the FPGA.

These are the existing `residual_sink_free` snapshots, not newly transformed
inputs and not necessarily reciprocal graphs. Their historical construction
adds one self-loop to every zero-outdegree vertex. For example, the AU
`materialization_manifest.json` records
`projection=add_self_loop_to_each_zero_outdegree_vertex_v1` and 436001 added
self-loops. Consequently this matrix must be described as sink-completed
ResPR workloads, not unmodified directed datasets. Both systems receive the
same frozen files; graph SHA-256 identities are in `matrix-inputs-zfs-v3/plan.json`.

For a quick independent source-coverage check of each frozen file:

```bash
LC_ALL=C timeout 600 awk '
FNR == 1 {
    if (NR > 1 && (rows != n || records != e + u)) exit 1;
    n = $1; e = $2; u = $3; rows = 0; records = 0; previous = -1;
    if (NF != 3 || n < 1 || u != 8) exit 1;
    next;
}
{
    records++;
    if (records <= e) {
        source = $1 + 0;
        if (source < 0 || source >= n || source < previous) exit 1;
        if (source != previous) rows++;
        previous = source;
    } else if (NF != 4 || $4 != 1) exit 1;
}
END { if (rows != n || records != e + u) exit 1; }
' /data/tmp/chuxiao/fullgraph_fpga_workloads_20260806/{au,su,wk,so,pk,lj,lj08,r19}_residual_pagerank_insert_u8.graph
```

This constant-memory source-coverage check is not a complete graph parser or
a PageRank numerical oracle. An earlier full-field diagnostic hit its
180-second execution timeout without a result; the completed source-coverage
scan above exited zero under a 600-second timeout. Neither run supplies
performance numbers for the FPGA comparison.

### Resident Timing And Repetitions

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
| `source-v1/results.json`, `hls-v1/results.json` | Original passing checks/exports; runner hashes predate the guard correction |
| `source-zfs-v3/results.json` | Passing executable checks with corrected guard |
| `hls-zfs-v3/results.json` | Both fresh passing cache exports; not routed timing |
| `route-zfs-v2/{sssp,cc,respr}/` | New links with exact ABI reviews and bounded admission |
| `spine-respr-zfs-v1/` | Compiler completed; original dependency-postprocessing failure retained |
| `spine-respr-zfs-audit-v1/` | Independent exact-binary/source/provenance/clock audit; routed, not board-tested |
| `matrix-inputs-zfs-v3/plan.json`, `matrix-zfs-v3/` | Current frozen 24-case plan and runner, waiting for exact new artifacts |
| `matrix-inputs-zfs-v2/plan.json`, `matrix-zfs-v2/` | Superseded and stopped before any board pair; eight ResPR rows were blocked by the wrapper failure |
| `route-v1` through `route-v4`, `route-zfs-v1` | Retained attempts; no completed new-kernel board result |
| `matrix-inputs-v1` through `matrix-inputs-v6`, `matrix-inputs-zfs-v1` | Historical immutable plans, not completed results |
| `matrix-v1` through `matrix-v5` | Stopped/incomplete matrices; zero board pairs |
| `sim-before/`, `sim-after/` | Separate Release component builds |
| `sim-sharded-v1/` | Fresh shared-metadata routing build and passing 31-test regression |
| `sst-sharded-v2/`, `sst-sharded-smoke-v1/`, `sst-sharded-payload-v1/` | Fresh default-plugin compatibility build and passing memory/payload probes; not a timing calibration |
| `sim-extent-benchmark-v1.csv` | Original portable component diagnostic |
| `host-control-au-v1/results.json` | OLD G+R kernel with the revised host |

The old-kernel AU control passes correctness with G+R 21.889057 ms and Spine
4.497250 ms median resident wall time (4.867209 times). It proves this control
runs correctly; it is not a new bounded-kernel measurement, an all-graph
result, or an isolated causal estimate of the host optimization.

Compiler trees are capped at 56 GiB (52-GiB high watermark), zero swap and
whole-group OOM termination. Admission keeps 24 GiB available and accounts
for complete finite peer budgets in addition to the new build's budget.
Historical complete G+R tree peaks were around
41--45 GiB. Concurrent compilers are admitted only if that total budget fits.
Board hosts have finite 16--32-GiB groups and share an exclusive board lock.
Interrupted `v1` runs and their logs are retained, not relabeled as passes.

### Spine Artifact Audit, Not Recompilation

The new sparse-apply Spine ResPR compiler completed successfully and produced
the expected three-kernel xclbin. Its wrapper then incorrectly treated the
HLS `compile-route` phase as ordinary C++ compilation and attempted to read
`respr.d`. The original report remains `FAILED_RETAINED`; the independent
integration-owned `validation/cache_extent/spine_recovery.py` verifies the
successful compiler step, unchanged source pins, sparse selector, provenance,
terminal success marker, binary kernels and clocks into a fresh audit.
Compiler failures, watchdog/OOM stops, changed inputs and failed binary
inspection are not recoverable through this path. Four focused tests and
the full 18-test cache/export/recovery suite pass. The real audit peaked at
125.5 MiB in a 2-GiB/zero-swap group.

Artifact SHA-256:
`b6cb210342029a77233740e7aeffea354d19757ebb68431b0fc993bef59bd15b`.
DATA is 150 MHz. The unscaled routed report has WNS -0.007 ns, TNS -0.014 ns
and three setup-failing endpoints, with no hold failures. Vivado automatically
reduced HBM from 450 to 448.6 MHz; xclbin metadata records 448 MHz. Do not call
this timing closure at the requested HBM frequency. The fresh `v3` matrix
uses this exact independently audited artifact and still requires board
correctness and paired measurements. The old failed report and blocked
matrix are not rewritten, no dummy dependency file was added, and no live
G+R build source or runner hash was changed.

### Memory-Guard Correction

The old watchdog used Linux `MemAvailable` alone. On this ZFS host that
omits most reclaimable ARC data, so it prematurely stopped builds even while
btop showed roughly 137 GiB available. These were guard stops, not evidence
of physical memory exhaustion or synthesis errors. The integration guide
retains the original per-attempt counters and failure paths.

The [shared memory probe](../../../../../implementation/runtime/host_memory_admission.md)
now adds only evictable ARC data, bounded by `ARC_size - c_min` and remaining
physical RAM. It excludes ARC metadata/anonymous entries and falls back to
raw Linux values on absent/invalid ARC counters. Both compile admission/live
watchdogs and the Spine shell preflight use this policy. Single-job limits,
zero swap, the 24-GiB reserve and full peer-budget accounting remain enforced;
no system-wide ZFS setting was changed.

The actual build-runtime worktree is branch
`codex/production-board-zfs-guard-20261025` at `07f8863`, containing main's
`341ad41` memory fix. G+R uses `7975080` plus mixed-budget peer fix `196060f`;
Spine's pinned shell probe is `9e5cb2b`. The 13 memory-helper tests retain the
two preexisting heap-release tests. Source/HLS stages still require exactly
1/8 GiB; their peer validator now accepts the existing bounded 56-GiB build.

`route-zfs-v1` rejected the old export's changed runner hash before linking.
`source-zfs-v2` rejected the larger bounded peer before compilation. Both
are retained failures. Fresh source and HLS gates must pass before another
link: no historical gate is repinned, and no old kernel fills a missing row.

Three historical G+R jobs received independent copies of the corresponding
previous build's Vivado IP compilation cache to reduce redundant synthesis.
Each output's `ip-cache-seed.json` retains a byte-checked source inventory;
the integration guide records the inventory hashes and original paths.
Vivado independently checks cache fingerprints before using an entry. This
does not reuse an old xclbin, replace the new bounded cache XO or establish
board performance. Original failed evidence and compiler caches are intact.

The current queued `route-zfs-v2/cc` and `route-zfs-v2/respr` jobs also
received independent compiler-cache copies on 2026-10-25. The copy held the
same admission lock as the compiler supervisors and checked live PID/start
identity, absence of an admission lease, waiting status and no compiler
outputs before and after copying. The prior inventory's complete member set,
sizes and SHA-256 values matched, with separate source/destination inodes.

| Current output | Files | Logical bytes | New `ip-cache-seed.json` SHA-256 |
| --- | ---: | ---: | --- |
| `route-zfs-v2/cc` | 848 | 937262532 | `71da84390731441152ca71db2917b01345602f85fe0ea0bbf3b0f4e78be6245c` |
| `route-zfs-v2/respr` | 909 | 1439763700 | `e14849683a398ff63bc29a1fdd40fb5f1f1a80f1c268f42e50ec5e661006867c` |

The retained helper is `seed-queued-ip-cache.py` under the live root
(SHA-256 `8a74d96cda17e6af361ff5f04e35e6131eb920524cd8c61af4d4f35682e99a64`).
Both copies completed under a 2-GiB hard/1.5-GiB high/zero-swap group,
peaking below 12 MiB. The source inventories and original directories are
recorded in the new seed reports. Live kernel XOs, configurations, runner
pins and the in-progress SSSP/Spine projects were not changed. A seed report
describes the initial cache only: Vivado may subsequently update its private
copy. Reuse remains subject to Vivado's fingerprint check.

No large bitstream or raw compiler log is checked into this repository.
The integration guide owns runner commands; immutable manifests above retain
the exact arguments and source hashes. This guide and the portable CSV are
the reviewable simulator-side entry point, not a substitute for pending board
evidence.

## Terminal Board Delivery

The integration repository's `validation/cache_extent/delivery.py` owns the
final portable export (commit `7a52eba`). It refuses a running matrix and
retains every one of the 24 terminal rows, including blocked or failed cases.
Before admitting a speedup, it checks immutable source, host, bitstream and
graph hashes, reparses all four paired raw logs and recomputes the measured
medians. The exported folder contains an overall README, a 24-row CSV with
actual data frequencies, copied reports/manifests/logs and a file-hash index.
Large bitstreams, graphs and compiler trees remain at the indexed original
locations. Twelve cache-study/export tests pass, including rejection of old
kernel controls, changed logs/hashes and unfinished or duplicated matrices.
This exporter has not yet packaged the pending new-kernel board matrix;
there is still no claim of completed FPGA results at this checkpoint.

### Hardware Speedup Preview

After exporting the terminal evidence, render it independently of the paper:
Use an environment with the project's `plots` extra and LaTeX `txfonts`
installed; the original handoff environment is
`/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python` on this machine.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.fpga_plot \
  --delivery /path/to/exported-fpga-results \
  --output /path/to/fresh-preview
```

The renderer uses the earlier Python handoff's TX Typewriter font, eight-fold
hatch patterns and black outlines. All eight dataset groups contain adjacent
ResPR, CC and SSSP positions. The log-scale ratio is measured median G+R wall
time divided by measured median Spine wall time; one marks equal performance.
Slowdowns remain below one. Failed cases retain their positions and are marked
with an `x`, not assigned zero, projected or copied from an older experiment.
The parser checks delivery-file hashes, complete matrix coverage and each CSV
median/ratio against the terminal report. Pending matrices and matrices with
no measured pair are rejected. PNG, PDF and renderer/input provenance are
written to a fresh directory. Unit fixtures only test validation; they are not
board results or replacement figure data.
