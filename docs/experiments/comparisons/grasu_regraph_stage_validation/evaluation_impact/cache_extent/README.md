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
| Revised G+R SSSP, CC, ResPR hardware | All three `route-zfs-v2` artifacts complete; ResPR metadata records DATA 149/HBM 432 MHz after automatic scaling, with an independent artifact audit |
| Sparse-apply Spine ResPR hardware | Compiler and artifact audit passed; independent AU board correctness passed, not a paired speedup |
| New-kernel FPGA comparisons | All eight SSSP pairs, all eight CC pairs and ResPR AU/SU/WK/SO passed (20 of 24 total); ResPR PK running; all four admitted ResPR cases have zero residual propagation rounds; SSSP SO has a large retained timing outlier |
| Production SST bounded-cache option | Explicit, default-off wiring and five real-SST checks passed; not FPGA-cycle calibrated or promoted into frozen figures |

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

The SST plugin now exposes the configuration explicitly, with defaults still
off. The separate functional checks below do not establish new FPGA timing
calibration. Timing differences caused by real HBM, host scheduling and
physical routing remain empirical questions for the new board matrix.

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

A fresh, separately built SST plugin exercises this opt-in simulator path,
as described below. Frozen production plugins and calibration contracts are
unchanged. Functional SST execution, core regression, HLS synthesis and
matched FPGA timing are distinct evidence gates.

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

### SST Opt-In Functional Validation

The fresh `sst-bounded-v1/libspine_cycle.so` exposes four explicit settings
through `sst/grasu_regraph_vertical.py`:

| Environment variable | Default | Meaning |
| --- | ---: | --- |
| `GRASU_SST_COMPACT_PARALLEL_SEARCH` | `0` | Select the finite parallel-search topology |
| `GRASU_SST_COMPACT_SEARCH_CONTEXTS` | `16` | Select 16 or 64 search contexts per CU |
| `GRASU_SST_COMPACT_CACHED_HOT` | `0` | Select the full-capacity hot cache |
| `GRASU_SST_COMPACT_CACHE_VALID_EXTENT` | `0` | Bound transfers to the rounded valid span |

The result's `update_observability.configuration` records all four settings
and the physical cache capacity. Core validation rejects bounded transfers
without the cached topology, or a short PMA layout requesting the old
full-cache transfer. No historical profile is silently upgraded.

The [opt-in integration suite](../../../../../../tests/test_sst_cached_update.py)
uses the exact requested plugin search path and records its SHA-256, input
hashes, command, environment, raw stdout/stderr and JSON for every invocation.
The five tests perform seven SST invocations on the existing fixture: one
insertion and one deletion. The backend is actual SST memHierarchy/DRAMSim3,
not the mock-memory component benchmark above.

| Configuration | Update cycles | PMA reads / writes | Backend requests |
| --- | ---: | ---: | ---: |
| Bounded cache, 16 contexts | 98 | 32 / 32 | 68 |
| Bounded cache, 64 contexts | 98 | 32 / 32 | 68 |
| Bounded cache, two touched destination shards | 182 | 48 / 48 | 100 |
| Default topology, frozen and new plugin | 54 | 2 / 2 | 8 |

All successful cases pass final-graph correctness and request conservation;
the two illegal configurations fail with their expected validation errors.
The default new-plugin JSON is identical to the frozen baseline after removing
only the new configuration object, including cycles, counters, final state and
backend statistics. These tiny update-only cases do not execute ReGraph or
validate total-system timing. Their outputs explicitly retain
`execution_driven_update_engine_sst_hbm_not_cycle_calibrated`.

The first `sst-bounded-verification-v1/` suite retained a failed test
expectation: it demanded a nonzero legacy `partition_routes` counter from
host-selected single-window shard children. That counter does not describe
this path. The real sharded run itself passed correctness and conservation.
The corrected test checks two touched shards and all 48 reads/writes; the
fresh `sst-bounded-verification-v2/` suite passes all five tests in 1.345 s.
No model timing or hardware source was changed to make that test pass.

The new plugin SHA-256 is
`0da332ef86a40e44b3555a89de9e4ed1d340a8722de2fbafc185b6678849fa39`.
Its build completed in a 2-GiB hard/1.5-GiB high/zero-swap group, peaking at
1013.9 MiB. The before-edit source archive is `sst-bounded-before-v1.tar`;
the old `sst-sharded-v2/` plugin remains intact. To reproduce the opt-in tests
from the repository root with separately built new and old libraries:

```bash
SPINE_SST_CACHE_TEST_LIBRARY=/path/to/fresh-plugin-directory \
SPINE_SST_CACHE_BASELINE_LIBRARY=/path/to/frozen-baseline-directory \
SPINE_SST_CACHE_TEST_OUTPUT=/path/to/fresh-test-output \
python3 -m unittest discover -s tests -p test_sst_cached_update.py -v
python3 -m unittest discover -s tests -p test_sharded_runtime_wiring.py -v
```

Without an explicit new library directory, the five optional SST tests skip;
the four parameter/placement wiring tests do not require SST. Neither this
suite nor the plugin hash replaces the frozen v20 calibration contract or
generates new figure data.

## Frozen Hardware Matrix

Twenty-four pairs cover SSSP, CC and ResPR on AU, SU, WK, SO, PK, LJ, LJ08
and R19. Each starts from the same old converged state, applies the same
eight-edit batch, and runs until the new result converges. CC encodes eight
undirected insertions as sixteen reciprocal directed records; both native
hosts report sixteen in their raw `logical_updates` and `physical_updates`
fields. These fields count input records, not undirected pairs. SSSP and
ResPR each have eight directed records. ResPR uses the shared fixed
threshold `1e-6`, not threshold divided by vertex count.

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
| `spine-respr-au-smoke-v1/` | Independent AU board correctness of the audited binary; not a paired measurement |
| `matrix-inputs-zfs-v3/plan.json`, `matrix-zfs-v3/` | Current frozen 24-case plan and live runner; completed measurements are listed in the paired-results sections below |
| `independent-pair-audit-v1/` | Saved three-pair checkpoint, frozen plan and independent raw-log/hash/clock recheck; not a terminal matrix export |
| `independent-pair-audit-v2/` | Saved four-pair checkpoint and independent recheck, retaining all measured samples and variability; not a terminal matrix export |
| `independent-pair-audit-v3/` through `independent-pair-audit-v6/` | Saved five- through eight-pair SSSP checkpoints, with independent raw-log, pin and clock verification |
| `independent-pair-audit-v7/` | Nine-pair checkpoint including CC AU, rechecked by the corrected input-record verifier; not a terminal matrix export |
| `independent-pair-audit-v8/` | Ten-pair checkpoint including CC AU/SU, independently rechecked against the same frozen plan; not a terminal matrix export |
| `independent-pair-audit-v9/` | Eleven-pair checkpoint including CC WK; additionally verifies saved memory containment, admission and zero OOM counters; not a terminal matrix export |
| `independent-pair-audit-v10/` through `independent-pair-audit-v12/` | Saved twelve- through fourteen-pair checkpoints including CC SO/PK/LJ, with independent raw-log, pin, clock and saved memory-contract verification; not terminal matrix exports |
| `independent-pair-audit-v13/` through `independent-pair-audit-v17/` | Saved fifteen- through nineteen-pair checkpoints, completing CC and adding ResPR AU/SU/WK; each independently rechecks raw logs, pins, clocks and saved memory contracts; not terminal matrix exports |
| `independent-pair-audit-v18/`, `independent-pair-audit-v19/` | Fresh nineteen- and twenty-pair checks with the propagation-aware verifier; the latter adds ResPR SO and retains all formal round counts; not terminal exports |
| `matrix-inputs-zfs-v2/plan.json`, `matrix-zfs-v2/` | Superseded and stopped before any board pair; eight ResPR rows were blocked by the wrapper failure |
| `route-v1` through `route-v4`, `route-zfs-v1` | Retained attempts; no completed new-kernel board result |
| `matrix-inputs-v1` through `matrix-inputs-v6`, `matrix-inputs-zfs-v1` | Historical immutable plans, not completed results |
| `matrix-v1` through `matrix-v5` | Stopped/incomplete matrices; zero board pairs |
| `sim-before/`, `sim-after/` | Separate Release component builds |
| `sim-sharded-v1/` | Fresh shared-metadata routing build and passing 31-test regression |
| `sst-sharded-v2/`, `sst-sharded-smoke-v1/`, `sst-sharded-payload-v1/` | Fresh default-plugin compatibility build and passing memory/payload probes; not a timing calibration |
| `sst-bounded-before-v1.tar`, `sst-bounded-v1/` | Before-edit source freeze and separately built opt-in SST plugin; old plugins intact |
| `sst-bounded-probe-v1/`, `sst-bounded-verification-v2/` | Actual SST bounded/sharded/default/negative tests, raw logs, exact plugin/input hashes; functional evidence, not FPGA calibration |
| `sst-bounded-verification-v1/` | Retained initial test-expectation failure on the legacy router counter; underlying sharded run passed |
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

### Revised SSSP Route Evidence

On 2026-10-25, `route-zfs-v2/sssp/results.json` reached
`ROUTED_NOT_BOARD_TESTED`: compiler exit zero, no watchdog stop and no cgroup
memory events. The bounded-cache xclbin SHA-256 is
`ed674b033c738506bd8ac32da9ab2b51e3e70e8925113aed048f50eb35dbf11e`.
Actual metadata retain DATA 150 MHz and HBM 450 MHz without downscaling.

The final `hw_bb_locked_timing_summary_routed.rpt` under
`work/link/vivado/vpl/prj/prj.runs/impl_1/` reports setup WNS +0.002 ns,
TNS zero and no setup-failing endpoints; hold WNS +0.009 ns, THS zero and
no hold-failing endpoints. All user-specified timing constraints are met.
Intermediate negative-slack messages do not supersede that final report.
This is a routed-artifact gate, not board correctness or a measured speedup.
The separate matrix uses this exact binary. The remaining algorithms have
separate artifact and board gates below.

### CC And ResPR Routed Timing Checkpoint

On 2026-10-26, both remaining links completed routing and DFX DRC with zero
errors. Their final routed timing reports, before any automatic frequency
scaling, contain:

| Algorithm | Setup WNS (ns) | TNS (ns) | Setup-failing endpoints | Hold WNS (ns) | Hold-failing endpoints |
| --- | ---: | ---: | ---: | ---: | ---: |
| CC | +0.001 | 0 | 0 | +0.009 | 0 |
| ResPR | -0.089 | -1.447 | 52 | +0.006 | 0 |

The reports are under each algorithm's
`route-zfs-v2/<algorithm>/work/link/vivado/vpl/prj/prj.runs/impl_1/`, named
`hw_bb_locked_timing_summary_routed.rpt`. Their SHA-256 values are:

- CC: `84805f408b449ec360fe98f419f136165fe64ca7f615c5fdb0b0e3e0aff10d2e`.
- ResPR: `1c54e388ca5b87a4e15f217c5455c9a8fe19ddfac653486d3ce63f718fbf2d47`.

CC subsequently completed bitstream generation and xclbin packaging. Its
`route-zfs-v2/cc/results.json` is `ROUTED_NOT_BOARD_TESTED`: compiler exit
zero after 15252.401 seconds, peak process-tree RSS 31624972 KiB, no watchdog
stop, no cleanup error and no cgroup memory events. The xclbin SHA-256 is
`3861b17a64de1b796feec4c230c89fb2f811492bd596819e315655804471f3e0`.
An independent `xclbinutil` extraction, `cc-artifact-clocks-v1.json` under
the live root, confirms DATA 150 MHz and HBM 450 MHz; its SHA-256 is
`3806667118e96bca9a259f8ab3599c33eb5ebe9a205312dec5ddd3a17f9ffac4`.
The existing strict routed-timing checker also accepts this final CC report.
This admits the artifact to testing, not a CC performance or correctness claim.

The existing routed-timing checker accepts CC and rejects ResPR at the
requested frequencies. ResPR's failures comprise 18 DATA-clock endpoints
(WNS -0.006 ns) and 34 HBM-clock endpoints (WNS -0.089 ns), with no hold or
pulse-width failures. This is not closure at DATA 150/HBM 450 MHz. The
subsequent `runme.log` and `_new_clk_freq` explicitly record automatic
frequency scaling to DATA 149.8 MHz and HBM 432.7 MHz; these values are not
inferred from slack. The link subsequently completed with compiler exit zero
after 20923.456 seconds, peak process-tree RSS 37283328 KiB, no watchdog stop,
no cleanup error and zero cgroup memory events. Its result is now
`ROUTED_NOT_BOARD_TESTED`, not a requested-frequency closure claim.

The completed binary is
`route-zfs-v2/respr/grasu_regraph_residual_pagerank.hw.xclbin`, SHA-256
`c112e790c3cfd81c05b4059f1dc34fcee23bc36a94a995ba1c0d6d49280058c0`.
An independent `xclbinutil` extraction records integer DATA 149 MHz and
HBM 432 MHz in `respr-artifact-clocks-v1.json`, SHA-256
`505df723ea758f6de63b745a929ed822b82c1867eada6de31b43ae8e70914511`.
`respr-artifact-audit-v1/results.json` separately rechecked the compiler's
terminal records, all 1396 unique pinned files including the final binary,
the unscaled timing report and clock dump. It passed under a 1-GiB
hard/768-MiB high/zero-swap group with zero memory events. The artifact is
ready for its AU board gate, not already board-correct. Measurements retain
the packaged clocks without scaling wall times to 150 MHz. Neither routed
reports nor SSSP pairs establish CC/ResPR performance.

### First Paired Hardware Results

All eight SSSP graphs have each passed one warmup and three measured
pairs. The following medians exclude the warmup and retain host relaunch and final
readback. Both architectures start from the old converged distances, apply
eight insertions and converge with zero mismatches. AU, SU, PK, LJ08 and R19 take two
hardware rounds on each architecture; WK and SO take one on each, and LJ
takes three on each.

| Dataset | G+R median wall (ms) | Spine median wall (ms) | G+R / Spine |
| --- | ---: | ---: | ---: |
| AU | 18.519382 | 4.302790 | 4.304040 |
| SU | 27.683435 | 4.335280 | 6.385616 |
| WK | 27.489030 | 4.525010 | 6.074910 |
| SO | 751.955400 | 18.033600 | 41.697465 |
| PK | 617.562590 | 8.197890 | 75.331895 |
| LJ | 2891.509930 | 32.427600 | 89.168176 |
| LJ08 | 1851.968107 | 20.446800 | 90.574961 |
| R19 | 78.411659 | 4.044650 | 19.386513 |

These eight rows were independently rechecked through the delivery verifier:
all four raw paired logs were reparsed, measured medians recomputed, and
manifest/source/host/bitstream/input hashes and actual clock dumps checked.
Both DATA clocks are 150 MHz. Evidence lives in
`matrix-zfs-v3/sssp-{au,su,wk,so,pk,lj,lj08,r19}/`, including `results.json`, `manifest.json`,
clock dumps and four `sample-*` directories. The saved independent recheck
is `independent-pair-audit-v6/results.json`, alongside its exact matrix
checkpoint and plan. It verified 1475 unique pinned files, exited zero in
15.139 seconds and peaked at 29.2 MiB process RSS under a 1-GiB
hard/768-MiB high/zero-swap group, with zero memory events. The additional
files are SO, PK, LJ, LJ08 and R19's generated configurations. Its status explicitly
excludes matrix completion; the earlier three- through seven-pair audits
are retained.

SO's three measured Spine walls are 15.5080, 18.0336 and 73.8605 ms, giving
a coefficient of variation of 75.23%; G+R's is 1.10%. The slow Spine sample
passes correctness and remains included in both the median and raw evidence.
WK's Spine coefficient of variation is 9.30%. CPU affinity is fixed to cores
0--3 but not exclusive, and compilation/other users' work can overlap these
measurements. The evidence does not identify the cause of the SO outlier;
do not claim stable isolated latency or silently discard it. Any follow-up
repetition needs a separate declared run, not replacement of this matrix.

This completes the declared eight-graph SSSP matrix, not the three-algorithm
study or proof of an isolated cache-optimization speedup. It must not be mixed
with the older full-cache control. The sixteen declared CC/ResPR pairs are
a separate gate; their first results follow below.
PK's three measured walls are 617.562590, 617.141686 and 618.312945 ms for G+R,
and 8.14950, 8.19789 and 8.72169 ms for Spine. Their coefficients of variation
are 0.0784% and 3.10%, respectively. SO and PK completed under their 32- and
24-GiB hard caps with zero memory events.
LJ's three measured walls are 2891.509930, 2892.872392 and 2889.139468 ms
for G+R, and 31.0370, 32.7241 and 32.4276 ms for Spine. Their coefficients
of variation are 0.0533% and 2.29%, respectively. LJ completed under its
32-GiB hard cap with zero memory events.
LJ08's three measured walls are 1851.968107, 1855.682326 and 1848.811729 ms
for G+R, and 22.8283, 20.2391 and 20.4468 ms for Spine. Their coefficients
of variation are 0.1516% and 5.55%, respectively. LJ08 also completed under
its 32-GiB hard cap with zero memory events.
R19's three measured walls are 78.475284, 78.257868 and 78.411659 ms for G+R,
and 4.07231, 3.89062 and 4.04465 ms for Spine. Their coefficients of variation
are 0.1164% and 2.00%, respectively. R19 completed under its 16-GiB hard cap
with zero memory events; the queue automatically advanced to CC AU. No live
cap, pin, or admission threshold was changed to force admission.
All three revised G+R artifacts are now available to the queue. No terminal
figure package has been exported.

### Complete CC Hardware Pairs

All eight CC graphs passed their warmups and three measured pairs with
zero mismatches and DATA clocks of 150 MHz. AU, SU, SO, PK, LJ and LJ08 need one
propagation round on each architecture; WK and R19 need two on each:

| Dataset | G+R median wall (ms) | Spine median wall (ms) | G+R / Spine |
| --- | ---: | ---: | ---: |
| AU | 11.873282 | 82.344700 | 0.144190 |
| SU | 15.154997 | 81.735600 | 0.185415 |
| WK | 75.355182 | 132.312000 | 0.569526 |
| SO | 823.085436 | 112.630000 | 7.307870 |
| PK | 305.140115 | 89.550700 | 3.407457 |
| LJ | 960.585233 | 95.996100 | 10.006503 |
| LJ08 | 923.044838 | 100.254000 | 9.207062 |
| R19 | 91.592355 | 109.287000 | 0.838090 |

On AU, Spine is slower by approximately 6.94 times. Its measured samples are
83.1385, 81.9327 and 82.3447 ms; G+R's are 11.920064, 11.694188 and
11.873282 ms. Their coefficients of variation are 0.607% and 0.823%,
respectively. The CC AU group completed with no memory events under its
16-GiB hard cap. These timings are retained without substitution by event
durations or a more favorable host variant.

On SU, Spine is approximately 5.39 times slower. Its measured samples are
80.7693, 82.5792 and 81.7356 ms; G+R's are 15.193249, 15.154997 and
15.143866 ms. Their coefficients of variation are 0.905% and 0.139%,
respectively. Both hosts report sixteen input records and one propagation
round in every pair. This is a measured resident comparison, not a prediction
of what a separately optimized CC host would achieve.

On WK, Spine is approximately 1.76 times slower. Its measured samples are
133.85, 129.383 and 132.312 ms; G+R's are 75.355182, 75.703571 and
75.224404 ms. Their coefficients of variation are 1.405% and 0.268%,
respectively. All four pairs report sixteen input records and two propagation
rounds on both architectures. The 16-GiB group completed with zero memory
events. The queue advanced to CC SO without replacing any measured sample.

On SO, Spine is approximately 7.31 times faster. Its measured samples are
112.281, 114.48 and 112.63 ms; G+R's are 823.797977, 823.006849 and
823.085436 ms. Their coefficients of variation are 0.853% and 0.0432%,
respectively. All four pairs report sixteen input records and one propagation
round on both architectures. The 32-GiB group completed with zero memory
events, and the queue advanced to CC PK. These results do not establish an
all-workload CC win: the three smaller cases above favor G+R.

On PK, Spine is approximately 3.41 times faster. Its measured samples are
90.4531, 88.6957 and 89.5507 ms; G+R's are 305.140115, 305.402429 and
304.680658 ms. Their coefficients of variation are 0.801% and 0.0978%,
respectively. All four pairs report sixteen input records and one propagation
round on both architectures. The 24-GiB group completed with zero memory
events, and the queue advanced to CC LJ without changing its frozen plan.

On LJ, Spine is approximately 10.01 times faster. Its measured samples are
96.4645, 93.8666 and 95.9961 ms; G+R's are 959.928861, 962.534001 and
960.585233 ms. Their coefficients of variation are 1.185% and 0.115%,
respectively. All four pairs report sixteen input records and one propagation
round on both architectures. The 32-GiB group completed with zero memory
events, and the queue advanced to CC LJ08 without changing its frozen plan.

On LJ08, Spine is approximately 9.21 times faster. Its measured samples are
100.254, 100.804 and 99.7588 ms; G+R's are 923.044838, 921.264260 and
923.433051 ms. Their coefficients of variation are 0.426% and 0.102%,
respectively. All four pairs report sixteen input records and one propagation
round on both architectures. The 32-GiB group completed with zero memory
events, and the queue advanced to the final CC dataset, R19.

On R19, Spine is approximately 1.19 times slower. Its measured samples are
115.815, 108.628 and 109.287 ms; G+R's are 91.592355, 91.358990 and
91.719342 ms. Their coefficients of variation are 2.916% and 0.163%,
respectively. All four pairs report sixteen input records and two propagation
rounds on both architectures. The 16-GiB group completed with zero memory
events. The complete CC matrix therefore has four cases favoring Spine
(SO/PK/LJ/LJ08) and four favoring G+R (AU/SU/WK/R19); no loss is omitted.

The first measured AU Spine log reports 2.85992 ms dynamic device-event time
but 83.1385 ms resident wall time. The resident boundary deliberately keeps
host work, launch/wait and readback. This discrepancy is not evidence of a
pure kernel slowdown, nor enough to assign the complete difference to one
host function. The frozen CC host is `spine-resident-host-v7`, not the
SSSP-only `resident-scratch-v3/weighted_sssp.host` optimization. The matrix
keeps those originally declared binaries unchanged; a later optimized-host
experiment must be separate rather than replacing these samples.

### First ResPR Hardware Pairs

ResPR AU, SU, WK and SO passed one warmup and three measured pairs, with eight
directed insertion records and zero rank, degree or nonfinite mismatches:

| Dataset | G+R median wall (ms) | Spine median wall (ms) | G+R / Spine | Propagation rounds, both |
| --- | ---: | ---: | ---: | ---: |
| AU | 21.407410 | 53.835500 | 0.397645 | 0 |
| SU | 27.242188 | 52.652600 | 0.517395 | 0 |
| WK | 52.660617 | 64.281500 | 0.819219 | 0 |
| SO | 867.179300 | 193.487000 | 4.481848 | 0 |

Spine is approximately 2.51 times slower on AU, 1.93 times slower on SU and
1.22 times slower on WK, but 4.48 times faster on SO.
AU's measured samples are 20.841104, 21.479141 and 21.407410 ms for G+R,
and 53.8355, 53.0491 and 54.0927 ms for Spine. Their coefficients of variation
are 1.343% and 0.827%, respectively. SU's are 27.251839, 27.242188 and
27.135669 ms for G+R, and 52.6526, 53.0596 and 51.7923 ms for Spine, with
coefficients of variation of 0.193% and 1.006%.
WK's measured samples are 52.862293, 52.660617 and 52.650738 ms for G+R,
and 64.8915, 64.2815 and 63.6689 ms for Spine, with coefficients of variation
of 0.185% and 0.776%, respectively.
SO's measured samples are 867.179300, 872.318017 and 866.263973 ms for G+R,
and 178.376, 193.487 and 205.476 ms for Spine, with coefficients of variation
of 0.307% and 5.762%, respectively. Its excluded warmup is
865.788892/198.431 ms (G+R/Spine), not a fourth formal sample.

The fixed threshold is direct per-vertex `epsilon=1e-6`, not divided by the
vertex count; damping remains 0.85. Both hardware paths and the CPU oracle
report convergence with zero residual propagation rounds in all four pairs
for each dataset. G+R still executes its update/correction pipeline once.
These are resident update/correction/completion measurements, not evidence
of nonzero iterative residual propagation performance. No threshold, batch
or host binary was changed to manufacture propagation or a Spine win.

G+R's packaged DATA/HBM clocks are 149/432 MHz; Spine's are 150/448 MHz.
Measured walls are not frequency-normalized. AU/SU/WK use 16-GiB hard/14-GiB
high limits; SO uses 32-GiB hard/30-GiB high limits. All four groups completed
with zero swap, whole-group OOM containment and zero memory events. The
remaining four ResPR datasets are a separate, unfinished gate; PK is running.

### Independent Paired-Result Audit

`independent-pair-audit-v19/results.json` verifies all twenty completed
cases and eighty paired samples including warmups. Besides raw logs,
medians, clocks and 1552 unique pinned files, it validates each case's saved
hard/high limits, zero swap, whole-group OOM containment, admission and
per-process budget/reserve policy, and zero post-run OOM counters. The audit
took 15.491 seconds with 28.9-MiB process RSS under a 1-GiB hard/768-MiB high/
zero-swap cap, with zero memory events. Its propagation-aware verifier is
integration revision `7acad8f` (SHA-256
`d9139af14ec591d32ed5eb0524de066b2f7dc7686e8d8997a4f3f4ff463a5dad`).
The matrix snapshot SHA-256 is
`a7cddf3831694194ffaa93485cfeec3f2afe7195afa9688a23ec9c148e55f63d`;
the plan SHA-256 remains
`dcfa6e48f3db23f7ab6c213207c8f4a733093a1d8dd082ab055cc19bf5e57a92`.
Four ResPR cases remain unfinished; ResPR PK is running. This audit is a
read-only checkpoint, not a new board run or terminal delivery.
The earlier `independent-pair-audit-v7/` through `v18/` directories retain
their nine- through nineteen-case snapshots and exact verifier identities.

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

The integration-owned `validation/cache_extent/spine_smoke.py` then ran the
exact audited binary on the frozen AU input under the shared board lock and
a 16-GiB/zero-swap memory group. `spine-respr-au-smoke-v1/results.json` is
`SPINE_AU_RESPR_SMOKE_PASS`, with the original command, input/source hashes,
raw log, actual clocks and no OOM events. Its checked resident wall time is
52.6317 ms for eight insertions on 515281 vertices. Propagation iterations
are zero, so it validates startup, correction and final state for this batch,
not nonzero residual propagation, repeated timing or a G+R/Spine speedup.
It does not replace any of the 24 formal pairs. The integration package's
cache/export/recovery/smoke regression passes all 21 tests.

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

Before compilation began, the `route-zfs-v2/cc` and `route-zfs-v2/respr` jobs
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
final portable export. The original exporter is commit `7a52eba`; corrected
input-record checking is commit `1aadfa7`, with saved memory verification
added in `bca49d0`, on the independent
`codex/cache-extent-delivery-review` branch. It refuses a running matrix and
retains every one of the 24 terminal rows, including blocked or failed cases.
Before admitting a speedup, it checks immutable source, host, bitstream and
graph hashes, reparses all four paired raw logs and recomputes the measured
medians. The exported folder contains an overall README, a 24-row CSV with
actual data frequencies, copied reports/manifests/logs and a file-hash index.
Large bitstreams, graphs and compiler trees remain at the indexed original
locations. Twenty-six cache-study, recovery, smoke and export tests pass in
the corrected verifier worktree with the pinned production-board runtime
on `PYTHONPATH`; four resident-log parser tests also pass. Running broader
integration tests against simulator main instead fails imports for runtime
modules that live on that production branch; this is not a passing test run.
The export tests reject old kernel controls, changed logs/hashes,
unfinished or duplicated matrices, and missing or inconsistent memory/OOM
evidence. Nonzero `high`/`max` pressure counters are preserved and do not
alone count as an OOM. This checks saved records without requiring a
finished case's cgroup to remain alive.
This exporter has not yet packaged the running new-kernel board matrix.
The passing cases above do not constitute the complete 24-case delivery
and are not exported by relabeling pending cases as terminal.

The original exporter incorrectly required the raw `logical_updates` count
to equal eight, which would reject valid CC evidence with sixteen reciprocal
records. The correction validates both raw count fields against the frozen
workload's `updates` count, checks the eight-edit batch contract separately,
and exports distinct `batch_size` and `input_update_records` CSV columns.
All raw fields and timings remain unchanged. Tests admit all three declared
algorithms and reject even mutually matching host logs when their record
count disagrees with the frozen workload. The hash-pinned live board runner
and HLS worktree were not edited to apply this packaging-only fix.

The CSV now additionally retains all three formal `gr_rounds_samples` and
`spine_rounds_samples` (semicolon-separated) and their `propagation_scope`.
Zero rounds on both sides in every formal sample are explicitly labeled
`no_propagation_rounds`; this is update/correction/completion evidence, not
iterative propagation performance. A separate ResPR table and scope warning
are generated in the portable README. Failed rows keep blank counts, and
excluded warmups cannot change the formal-round classification. The eleven
delivery tests pass with the additional zero/nonzero-round and invalid-count
checks; their output is retained in
`propagation-scope-preflight-v1/tests.log` under the live root. This reporting
change does not modify the measured hosts, bitstreams, inputs or thresholds.

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
written to a fresh directory. These fixtures are synthetic tests, not board
results or replacement figure data.

The eight parser tests run without plotting dependencies. Two additional,
explicitly enabled rendering tests require the `plots` extra, Pillow, LaTeX
`txfonts`, and Poppler's `pdffonts`/`pdftotext`. They exercise all-slowdown and
wide-range/failure fixtures, check the embedded `txtt` font, expected numeric
ticks, nonblank colored PNG output and provenance, and reject overwriting an
existing preview. Retained fixture directories and `synthetic_test.json`
explicitly identify this non-performance scope:

```bash
SPINE_FPGA_PLOT_RENDER_TEST=1 \
SPINE_FPGA_PLOT_TEST_OUTPUT=/path/to/fresh-synthetic-tests \
python3 -m unittest discover -s tests -p test_cache_extent_fpga_plot.py -v
```

The visual smoke revealed that the original five-tick log locator skipped
decades and could label only one for a narrow range. The stronger numeric-tick
regression retained both failures in `plot-render-tick-regression-v1/`; the
renderer now retains every decade and uses 1/2/5 ticks for narrow ranges.
All ten tests pass in 4.760 s in `plot-render-smoke-v2/`, with a 177.1-MiB
service peak under a 2-GiB hard/1.5-GiB high/zero-swap group. Both previews
were visually inspected for layout. No measurement, running-matrix status,
source pin, historical figure or paper was changed by this rendering fix.

### Read-Only Event Diagnostics

The separate `evaluation_impact.fpga_profile` module consumes the same terminal,
hash-indexed export. It does not edit or measure a running experiment:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.fpga_profile \
  --delivery /path/to/exported-fpga-results \
  --output /path/to/fresh-event-diagnostics
```

`profile.json` preserves measured samples 1--3, their log paths and input hashes.
`profile_medians.csv` keeps every declared case, including failures with blank
metrics. The module separately reports GraSU event union, completion-barrier
event union where logged, total kernel event union, convergence readback where
logged, and resident wall time. ResPR's update event union includes the device
degree update; SSSP/CC report completion-barrier events separately. No unlogged
barrier or readback time is filled with zero.

`wall_variability.csv` contains 48 rows: both architectures for each declared
case. Each passing row retains all three measured wall times and recomputes
the minimum, median, maximum and population coefficient of variation
(`pstdev / mean`) against the admitted summary. The coefficient is a fraction,
not a percentage or confidence interval. Failed rows retain blank measurements.
This makes the retained SO outlier visible beside the speedup, without filtering
samples or assigning a cause to their variation.

The diagnostic **kernel-uncovered wall** is computed per sample as wall minus
total kernel event union, then summarized by its median. It includes DMA,
final-state readback and scheduling/launch gaps, and is **not pure host time**.
Medians of separate quantities need not add up. Individual adapter, gather,
apply and HBM durations overlap and are not summed into an artificial R stage.
These quantities neither identify a causal before/after improvement nor
establish publication matching or simulator stage calibration.

Sixteen synthetic tests cover overlapping intervals, absent ResPR metrics,
nonfinite/impossible intervals, excluded warmup, median-of-per-sample gaps,
hash-indexed raw logs, changed walls, terminal-only admission, retained failures
and non-overwriting output. They also check both architectures' variability,
retention of a slow sample, population rather than sample standard deviation,
rejection of changed summary statistics, and blank failed-case variability rows.
They pass without FPGA/plotting dependencies. The recomputation also accepts
both architectures' actual AU/SU/WK/SO/PK/LJ/LJ08/R19 measured-wall summaries
without changing those reports. The running board matrix has not been exported
as final event diagnostics. The analyzer reparsed all 60 measured G+R logs
from the eight SSSP, eight CC and first four ResPR cases against their admitted
per-sample walls, and rechecked all 40 architecture/case wall-statistic records.
The latest read-only check is retained in `profile-checkpoint-20-v1.log`:

| Algorithm | Dataset | G event-union median (ms) | Total kernel-event union median (ms) | Kernel-uncovered-wall median (ms) |
| --- | --- | ---: | ---: | ---: |
| SSSP | AU | 1.170615 | 17.982796 | 0.567027 |
| SSSP | SU | 1.663740 | 27.104028 | 0.579407 |
| SSSP | WK | 0.876866 | 26.639644 | 0.849386 |
| SSSP | SO | 15.781628 | 727.777370 | 24.178030 |
| SSSP | PK | 15.258602 | 616.337281 | 1.225309 |
| SSSP | LJ | 16.144347 | 2889.343838 | 2.269436 |
| SSSP | LJ08 | 12.613305 | 1848.953570 | 2.549083 |
| SSSP | R19 | 5.624992 | 77.831871 | 0.579788 |
| CC | AU | 1.134184 | 11.294995 | 0.560417 |
| CC | SU | 1.322839 | 14.628422 | 0.525935 |
| CC | WK | 2.236995 | 74.424774 | 0.930408 |
| CC | SO | 2.228865 | 820.374338 | 2.756839 |
| CC | PK | 2.224945 | 303.518448 | 1.649418 |
| CC | LJ | 2.185704 | 958.291216 | 2.294017 |
| CC | LJ08 | 1.852332 | 920.475145 | 2.816450 |
| CC | R19 | 2.199493 | 90.951757 | 0.688890 |
| ResPR | AU | 3.322216 | 20.357059 | 1.050351 |
| ResPR | SU | 3.130331 | 26.129807 | 1.121222 |
| ResPR | WK | 1.438732 | 51.055911 | 1.623346 |
| ResPR | SO | 12.113561 | 858.853890 | 7.812165 |

For example, CC SO's G event union is approximately 2.23 ms, whereas its
resident G+R wall median is 823.09 ms. This is not an isolated measurement
of adapter/R overhead or proof of original-GraSU performance matching.
Overlapping event unions and separately computed medians must not be added
or subtracted to manufacture an exclusive stage attribution. This is a
twenty-case diagnostic checkpoint, not a terminal 24-case profiling export.
The four ResPR cases have zero propagation rounds; their G event union includes
device degree update. Unlogged ResPR barrier/readback metrics remain absent.

The final-delivery preflight also passes nine integration export tests, ten
plot/parser tests including both optional LaTeX render checks, and sixteen
event/variability tests. Complete outputs are retained under the live root in
`final-preflight-v1/{delivery,plot,profile}-tests.log`, from the bounded
`gr-cache-{delivery,figure,profile}-preflight-20261026-v2.service` runs.
The earlier `v1` runs passed too, but their piped output was not retained in
the service journals; the fresh runs preserve it explicitly. Synthetic render
fixtures are under `final-preflight-v1/synthetic-plots-v2/`. Peak service
memory in the fresh runs was 15.3, 135.4 and 16.8 MiB, respectively, each
with a 1-GiB hard/768-MiB high/zero-swap limit. These 35 passing software
checks are not additional board measurements.
