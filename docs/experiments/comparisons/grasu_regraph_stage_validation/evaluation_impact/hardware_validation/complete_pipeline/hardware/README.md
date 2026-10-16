# Diagnostic Full G Link

## Scope

`g-complete-route-v1` is a fresh diagnostic hardware link, started concurrently
with the adapter-only `r-adapter-route-v3`. Its purpose is to test the
resource/timing feasibility of the reviewed search and full-cache exports in
the existing 150-MHz G+R topology. It is **not** yet a complete-G RTL,
production-baseline, board-performance or publication-match admission.

The inputs are eleven frozen XOs for 22 CUs. Only two XOs are replaced:

| Kernel | Evidence | XO SHA-256 |
| --- | --- | --- |
| `bin_search` (four CUs) | Eighteen wrapper RTL transactions and independently reviewed ABI | `d57b5827e2bbb09614e4bcd95fbe97adc79721db05e567820b6a9ac50eb39f1f` |
| `process_cache` (two CUs) | Six full-state wrapper RTL transactions, tokens and ABI | `caeb04635bc0eea9d36a04ebafb576d5b31ceb608b78f89acd206f218bfec9d8` |

The other nine XOs match the adapter-route basis, including the current
bank-streaming adapter. Both hot halves retain 131072 segments. The only
placement change is `lksg_stream_4:SLR0` to `SLR1`, justified by the
[storage screen](../resource_evidence/README.md). Memory mappings, stream
connections, kernel counts and clock are unchanged.

The composition and exported synthesizable search/cache cores are checked
against their frozen source. One exact host-only difference is recorded:
`HostReport` becomes `thread_local` in the concurrent C-simulation fixture.
`network.hpp` excludes that header under `__SYNTHESIS__`. No arbitrary host
or hardware drift is admitted. Separate control/testbench translation units
are not part of the shared hardware core.

## Concurrent Admission

Other FPGA tools need not exit when their budgets fit. Before vendor tools
start, the supervisor reserves the actual full compiler-cgroup memory budget
under a short atomic admission lock. It does not hold a global lock for the
lifetime of the route. Pending builds count even before a Vivado process is
visible; multiple processes in one cgroup count only once. A dead supervisor
does not free a lease while its compiler cgroup remains populated.

For this launch, one other route has a 40-GiB bound. Admission requires:

`40 GiB own + 40 GiB other route + 24 GiB system reserve + 8 GiB background = 112 GiB`

Eight consecutive two-second samples passed; the final sample recorded
135640289280 available bytes (about 126.3 GiB). Six environment preflight
checks passed and the link actually started. These are launch observations,
not a permanent guarantee of available memory or a completed route.

Each route has a 40-GiB hard / 36-GiB high cgroup limit, no swap and group OOM
kill. The owned process-tree watchdog samples RSS and global available memory
every two seconds, preserving a 24-GiB live reserve. It terminates only its own
workers on a guard violation. There are two synthesis/implementation jobs,
a six-hour link timeout, a 24-hour admission timeout and a 31-hour service
lifetime. Unbounded or unverifiable competing compilers fail admission.

## Monitor

The v1 attempt terminated at 2026-10-16 02:37 UTC because its six-hour
process-tree deadline expired during bitstream generation. Routing had
completed and the saved final timing report says all user constraints are met
(WNS 0.003 ns, TNS 0, WHS 0.006 ns). Nevertheless, there is no completed
`candidate.hw.xclbin`: the attempt remains `LINK_FAILED`, not a board or
baseline pass. All recorded cgroup `high`, `max`, OOM and OOM-kill counts are
zero; its peak cgroup usage was 29134856192 bytes. This was not a memory stop.
The dependent v1 board queue failed closed without programming a device.

No complete routed DCP was saved before termination, so the retry uses a
fresh output directory and repeats the link from the same admitted eleven
XOs. The CLI now accepts `--link-timeout-seconds 43200` for a twelve-hour
link, in addition to the unchanged six-hour default. Other values, noninteger
values and reused output paths are rejected. The 40-GiB hard bound, live
reserve, peer-budget admission, two jobs and all evidence gates are unchanged.
The enclosing service must allow the 24-hour queue plus the selected link
deadline and preflight/cleanup time. A longer deadline is not a timing waiver.

The fresh v2 retry uses the same concurrency rule; it does not wait for all
FPGA tools to exit. With both the original-R and A4 routes active, each bounded
at 40 GiB, its admission requirement is
`40 GiB own + 80 GiB peers + 24 GiB reserve + 8 GiB background = 152 GiB`.
At the 2026-10-16 05:28 UTC checkpoint, about 110 GiB was available, so it
remained queued. A small source-check job was admitted alongside both routes
because its full 1-GiB budget plus peers and reserve fit. Instantaneous peer
RSS is not substituted for enforceable limits; queueing is not route failure.

After A4 terminated, v2 passed its full-budget admission with the original-R
route still running: 135,659,524,096 available bytes against 120,259,084,288
required bytes (112 GiB). All eight safe samples and the environment preflight
passed; `execution.json` now reports `DIAGNOSTIC_ROUTING`. This is concurrent
execution, not a wait for all FPGA tools. The fresh service is
`spine-grasu-complete-route-20261016-v2.service`, invocation
`49a3071d4a9244ff8f83e3429295d2a1`, with raw output in `g-complete-route-v2/`.
It is not yet a terminal routed artifact or a hardware measurement.

Raw attempt:
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-complete-route-v1/`

Service: `spine-grasu-complete-route-20261016-v1.service`.
Invocation: `873fe3b111d3460b94457140f3df58be`.
Do not infer a pass from a running service's `Result=success`.

```bash
systemctl --user show spine-grasu-complete-route-20261016-v2.service \
  -p ActiveState -p SubState -p Result -p MemoryCurrent -p MemoryMax
cat /data/chuxiao/experiments/baseline_hardware_validation_20261015/g-complete-route-v2/execution.json
tail -n 30 /data/chuxiao/experiments/baseline_hardware_validation_20261015/g-complete-route-v2/route.stdout.txt
```

`manifest.json` pins every XO, configuration, validation report, launcher,
runner and explicit environment dependency. `execution.json` records actual
admission and status; `summary.json` and `route.resources.json` appear after
link termination. `cgroup_events.json` is saved when the supervisor exits.
A failed attempt stays failed. Never restart or overwrite this attempt.

## Verification

The focused regression suite passed all 187 tests, covering memory leases,
source identity, resource screens, export gates, route supervision and existing
component/cleanup contracts. It ran in a 2-GiB hard-limit, zero-swap cgroup;
sampled process-tree peak RSS was 93964 KiB. Raw logs and resource observations
are in `verification-concurrent-resource-v2/` beside the route attempts.
The separate repository-structure suite passed all 15 tests.

`verification-concurrent-resource-v1/` is retained as a failed test-launcher
attempt: its inherited 2-GiB virtual-address-space hard limit prevented three
cleanup tests from setting their child limits. The fresh v2 attempt used the
existing 64-GiB per-process address-space allowance while retaining the 2-GiB
physical-memory cgroup and tree watchdog. No assertions were relaxed. These
tests validate orchestration contracts, not integrated hardware correctness
or performance; neither live route has passed those gates yet.

## Reproduce And Next Gates

The thin entry point is:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware --help
```

It requires `--build`, `--basis`, `--search`, `--review`, `--cache`,
`--composition`, `--fit` and a fresh `--output`. Preparation is tool-free;
`--execute` requires a bounded service with the policy above. Preparation
revalidates the component exports, complete-state source composition and
platform storage ledger. The raw manifest records exact selected input paths.

The packages keep gates, source identity, input freezing, execution and memory
admission separate. Current route inputs are immutable while tools run.

## Production Source Boundary

The diagnostic link reuses exported search/cache XOs; it does not change the
production source-build scripts. At integration commit
`6f5ebf2b0679f04f4f6e035e850fce7b6043a660`, both
`scripts/prepare_pure_hw_pipeline_build.sh` and
`scripts/prepare_pagerank_pipeline_build.sh` still select
`repos/GraSU/GraSU/GraSU_kernels/src/kernel_bin_search.cpp` and
`kernel_process_cache.cpp`. Both request the old direct-cache compile mode.
Consequently, regenerating a production build with those scripts does not
reproduce the reviewed search/full-URAM-cache candidate merely because a
diagnostic route passes. That frozen build remains unchanged.

An isolated source candidate is now committed and pushed in the integration
repository as `3418e96` on `codex/complete-g-production`. Its
[source guide](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/3418e96/kernels/grasu_complete/README.md)
owns the implementation map, opt-in selection and verification commands.
The synthesizable core was copied from this simulator's reviewed
`cpp/tests/evaluation_impact/common_g/hls/` at `bb14f05`, with explicitly
enumerated binding/include transformations and reversible hash checks.
Both generators now accept `--grasu-implementation complete-search-cache`;
their default remains the legacy direct-cache implementation.

The candidate retains the eleven-argument search ABI, shared metadata master
and full 131,072-segment registered cache. SSSP/CC retain the completion-token
binding; PageRank retains its existing two-argument cache binding. Generated
manifests record source paths, selection, flags and source/dependency hashes.
The candidate requires hardware/hardware-emulation sharded-K4 builds at full
cache capacity and rejects unsupported combinations before creating outputs.

`g-production-source-selection-v5` passes seven bounded checks: both host
binding types, source identity, selection and three legacy build regressions.
It ran concurrently with the two routes under a 1-GiB hard / 768-MiB high
limit, zero swap and group OOM termination. Memory-event counters were zero;
maximum individual child RSS was 219536 KiB. The earlier failed source-check
launches remain retained in the campaign root. These checks do not compile
the search dataflow body with HLS, establish numerical equivalence or validate
new RTL. External weighted-SSSP UDF completeness is also a separate gate.

The non-synthesis search binding now requires an explicit compatible
`GRASU_SEARCH_HOST_HARNESS`; it still cannot use stock vendor streams as a
replacement for the finite concurrent harness. The cache uses the configured
upstream `kernel_config.h`, not a fixture-relative include. Fresh production
functional v5 now passes eighteen search checks and six full-state checks for
each cache binding. HLS v3 exports all three source-based components with
4.867-ns estimates at the rounded 6.67-ns target; full reference ABI review
passes for search/token cache, while plain cache passes its explicit
token-minus-completion derived contract. These isolated results do not replace
the frozen diagnostic XOs or close integrated finite-stream/backpressure RTL.

The new production RTL continuation runs from the identical frozen HLS cores,
fixtures and headers. Attempt v1 passed full-budget concurrent admission but
failed before any RTL transaction because HLS removed quotes from the host
harness's header-name compiler flag. Its logs and failure remain intact. A
frozen host-only preinclude fixes that launcher issue without changing kernels;
thirteen focused tests pass. Fresh v2 was admitted with both 40-GiB routes still
active (124271116288 available bytes against 120259084288 required). It uses
an 8-GiB hard / 7-GiB high bound, zero swap and the same 24-GiB live reserve.

Service: `spine-g-production-rtl-20261016-v2.service`.
Invocation: `42c27a70bef64799868a738cddcb3929`.
Raw output: `g-production-rtl-v2/` under the campaign root. Final RTL outcome
is pending. The integration repository's `validation/README.md` owns its CLI
and stage boundaries; no new production route or board pass is claimed.

Production changes belong in an isolated integration worktree while current
jobs pin the existing one. They must leave the current attempt's manifest,
inputs, runtime modules and failure records unchanged.

A successful link still needs timing/utilization review, complete G
backpressure/state and real-host validation, then physical PMA handoff,
continuous batches and board timing. G, adapter/R and host windows must be
measured separately before publication/source controls and new Spine speedups
are accepted. The existing adapter-only route cannot stand in for this route.
