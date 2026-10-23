# Current Bank-Stream R Against A4

## Scope

This is the complete-convergence counterpart of the
[resident bank-stream replay](../../actual_sharded_k4/model_sync/system/bank_stream/README.md).
It adds the current two-pair source topology to the existing
[credit sensitivity controls](../r_credits/README.md), without replacing them.
The earlier `candidate` arm has four source masters sharing two physical
banks; it is not the current seven-master topology.

Status at the 2026-10-22 checkpoint: the local simulator-only matrix is complete.
All 32 executions pass correctness/conservation; all 28 historical observations
replay exactly, and source/input/build pins remain unchanged. The current path
is **2.951 / 3.635 times slower than A4-io16**, so the requested approximately
10% retention gate is **not met**. This is a retained mismatch, not a completed
baseline validation. See the [compact evidence index](evidence/cpu_core_20261022_v2.json).

For the latest default-off correction, read the
[finite directory-lookahead result](prefetch_compact/DIRECTORY_OVERLAP.md).
It reduces complete cycles to 1.479 / 1.552 times A4 with all twelve correctness
and eight old-replay checks passing; the 10% retention gate still fails.
The historical seven-master result below is unchanged, not silently replaced
by that sixteen-master experimental architecture.

Earlier attempts remain separate: a strict local run was denied admission;
the first checked-core run hit a 120-second regression timeout before any
numerical row. Its replacement uses the original campaign's 600-second
per-test bound and passes all seven regressions. The independent remote run
was last seen running, but SSH is unavailable and no final return was retrieved.
None of those infrastructure states substitutes for the completed local result.
This study changes neither production model timing nor HLS. It does not
calibrate the simulator to FPGA or reproduce a published ReGraph number.

## Fixed Comparison

Every arm uses the same Amazon real-ID slice (258,046 vertices, 1,450,899
edges), old converged weighted-SSSP state and three source-0 weight decreases.
The updated graph and seed are resident. All arms must finish the same
46-round synchronous propagation and final shortest-path closure. The window
excludes G, preparation, DMA and host orchestration from both systems.

The predeclared matrix is eight arms, two mock memory latencies (64 and 128
cycles), and two component registration orders: **32 executions**. The seven
historical arms retain their configuration. `bank_stream` alone selects the
production `grasu_regraph_bank_stream_sssp_compute_v1` configuration factory:
four adapter masters, two pairwise source services and one Apply master;
1024 directory rows, 256 bank FIFO lines, reader/drain intervals of two,
16 parent credits and a 16-request Apply window. The harness asserts the
actual backend registration count: seven versus nine for old K4 controls.

Compare the new arm with both legacy A4 and `a4_io16`; do not select only the
closest result. A4 has 13 masters on nine banks and four property replicas.
The new K4 has seven masters and two source replicas plus primary state.
Equal frontend count or parent credits is not strict resource equivalence.
These mock-memory assumptions are sensitivity controls, not measured AXI
latencies or a complete SST/DRAMSim3 evaluation.

## Acceptance

- All **28** preceding observations must replay exactly, including every
  round's cycles/active count, traffic, full-state output hashes and extents.
- New forward/reverse results must match exactly. Every final state word,
  replica and active trajectory must equal the old synchronous oracle.
- The C++ harness checks edge/packet conservation, request/completion and
  beat closure, drained memory, Apply/source/status writes and physical bytes.
- Retain all declared rows, failures and timeouts. Fresh Release compilation,
  the configuration test and seven focused C++ regressions precede execution.
- Source/input/build hashes must remain unchanged through the campaign.

Passing admits this single compute prediction, not FPGA timing, strict
resource matching, original 11-Little/3-Big publication performance, complete
G+R or a replacement Spine speedup. Those flags remain false in the output.

## Completed Result

| Arm | 64-cycle memory: total cycles | 128-cycle memory: total cycles |
| --- | ---: | ---: |
| Original A4, legacy parent limits | 30,740,788 | 59,442,350 |
| Original A4, 16 edge/state parents | 10,904,254 | 15,840,606 |
| Current seven-master bank stream | 32,178,380 | 57,588,504 |
| Earlier nine-master candidate | 32,160,486 | 57,582,524 |
| Candidate, Apply window 2 | 53,168,456 | 96,684,180 |
| Candidate, source/edge parents 2 | 77,654,808 | 145,284,836 |
| Candidate, both limits 2 | 77,655,544 | 145,285,204 |
| Historical cross-row path | 244,269,384 | 431,605,442 |

Forward/reverse registration gives identical results for every arm. All finish
the same 46 rounds and final full-state hashes. Current/legacy-A4 is
1.0468 / 0.9688, but selecting that weaker control would conceal the stronger
A4-io16 mismatch. Switching four source masters to the actual pairwise topology
changes this case by less than 0.06%; it has not recovered the missing performance.

Across all 46 rounds, A4 reads 802,534,400 bytes and writes 192,937,984;
the current path reads 2,021,232,640 and writes 144,703,672. Reads increase
2.5186 times, while writes decrease because there are three rather than four
state copies. These ledgers alone do not attribute elapsed cycles. The completed
read-only diagnostic below retains the same results without reducing memory
latency or slowing A4. The compared resources remain different as listed above.

## Physical Layout Diagnostic

A read-only census of the unchanged CSR gives the following per-round layout.
Every nonempty `(source, destination-shard)` row fits one 16-slot segment;
there are 475,610 such rows for 1,450,899 live edges (3.05 edges per row).

| Destination shard | Live edges | Nonempty rows |
| --- | ---: | ---: |
| 0 | 848,130 | 179,508 |
| 1 | 370,883 | 155,926 |
| 2 | 170,898 | 98,910 |
| 3 | 60,988 | 41,266 |

The physical PMA requires 30,439,040 bytes per scan, plus 8,257,536 directory
bytes and 256 extent bytes. Slot/live-edge ratio is 5.245, **not** a byte ratio:
PMA slots are 32 bits, whereas compact A4 edges are 64 bits. The full measured
simulator ledger also includes source-state and Apply traffic. This census
does not attribute elapsed cycles or prove that a particular slowdown is
unavoidable. Unequal shard occupancy, directory/segment waits and downstream
backpressure need independent progress measurements before choosing a fix.

The census uses `csr_offsets.u32le` SHA-256
`d95fb029da4c365923ff6ffbf89a34df1a0935f7aa90a41bda17e9e85577ecd2`
and `csr_destinations.u32le` SHA-256
`23b0d9fb08d49778179cef50dc09b6873a1aede8bc6437de59c09fc154a29ba9`
from the frozen input below. It counts destinations by `dst // 65536` for
each source, rounds nonempty rows to 16 slots, and rounds directory tiles to
1024 rows. The standalone census used a 256-MiB/zero-swap scope and changed
neither the input nor the execution model.

## Read-Only Completion Diagnostic

The optional eighth argument of `regraph_convergence_demo` exports existing
`RoutedReGraphSystem::rounds()` and `invocations()` timestamps to a separate
empty directory. Default stdout and the three state outputs are unchanged.
No production component, scheduler call, memory latency or traffic is changed.
The exporter normalizes internal one-based invocation rounds to the zero-based
trajectory. `progress.py` checks complete unique records, assignments, window
closure, active counts and completion ordering. Endpoint durations overlap;
they must **not** be summed or called exclusive stage/stall attribution.

`diagnose.py` reuses the checked numerical libraries, freshly builds the
entry point and runs the four current-path cases. It requires exact replay
of the completed matrix's observations and state hashes, and identical
completion records across registration orders. Progress CSVs live outside
the state directory so they cannot silently change the state-file ledger.

All four executions now pass exact replay, including full state, traffic and
active trajectories. Source/input/build pins are unchanged. The complete scope
peaked at 1,192,955,904 bytes with zero swap under a 4-GiB hard limit. See the
[completion evidence index](evidence/progress_20261022_v2.json).

The following are sums of completion offsets from each of the 46 round starts,
not sums of exclusive stage durations:

| Completion endpoint | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| Last adapter | 25,664,688 | 45,045,362 |
| Last frontend compute | 32,151,562 | 57,540,848 |
| Apply done | 32,175,022 | 57,582,202 |
| Writeback done | 32,178,334 | 57,585,514 |
| Status / round end | 32,178,380 | 57,588,504 |
| Tail after last frontend | 26,818 | 47,656 |

The final tail is below 0.1% in both cases. This excludes final drain alone
as the explanation for the approximately three-times mismatch. It does **not**
show that Apply is free: downstream backpressure overlaps frontend execution.
Worker 0 is the last adapter, but worker 3 is the last compute frontend despite
having the fewest edges. Consecutive frontend completions are spaced by 35,328
or 68,096 cycles per round, consistent with the existing partition-ordered
gather drain. Endpoint records do not isolate causal stall cycles.

The shared Apply master's combined read/write credit limit is an explicit
limitation of the existing routed profile, not a newly discovered accidental
setting. Changing it would be a separate resource control, not a timing fix.

The later [passive wait study](prefetch_compact/OBSERVATIONS.md) replays all
twelve compact-convergence rows exactly. It records source-consumer
backpressure and full Apply windows without changing timing or resources;
these observations overlap and are not an exclusive stage breakdown.

The subsequent [independent source-cache loading study](prefetch_compact/SOURCE_LOADING.md)
completes sixteen convergence executions, exactly replays all twelve pre-edit
controls, and passes fresh core/default SST compatibility. It removes source
output stalls but improves total cycles by only 2.78% / 2.16%, leaving
**2.519 / 2.150 times strong A4**. The approximately 10% gate still fails;
the schedule is default-off and not a replacement baseline.

The later [reader-port diagnostic](prefetch_compact/READER_PORTS.md) isolates
physical input bandwidth; it does not promote a new complete-R path. The
[full-burst refill experiment](prefetch_compact/BURST_REFILL.md) next tests
request fragmentation with unchanged physical bytes and finite rings. Both
retain the strong A4 reference and distinguish reader floors from complete
convergence. Simulator-only investigations do not require FPGA builds.

The bounded adapter-only diagnostic below further isolates that reading path.
Its result rules out a downstream-only fix on this input. Additional inputs
and stricter resource controls remain open.

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-progress-NEW \
  -p MemoryMax=4G -p MemoryHigh=3G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=1h -p CPUAffinity='124 125 126 127' \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.diagnose \
  --output /data/chuxiao/experiments/r_bank_stream_comparison_20261022/progress-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --core-gates /data/chuxiao/experiments/sharded_k4_bank_stream_profile_20261019/gates-v1 \
  --cpus 124 125 126 127 --admission-wait-seconds 600
```

The pre-instrumentation source archive is retained as
`/data/chuxiao/experiments/r_bank_stream_comparison_20261022/pre-progress-source.tar.gz`,
SHA-256 `226af5d1c169f7bae6a8a27da57f1e4198160f831256925dd9609406e3eb1ff1`.
Its completed reference is immutable. The first diagnostic attempt was denied
admission with no build or numerical rows: 73.58 GiB available versus 80 GiB
required. Its older runner labels that infrastructure-only event
`FAILED_RETAINED`; the corrected runner explicitly distinguishes admission denial.

## Ownership And Reproduction

### Stall-Free Adapter Diagnostic

`adapter_floor.py` builds a separate diagnostic entry point against the same
checked numerical core. Four actual production adapters retain the current
runtime map, physical PMA/directory reads, AXI credits, latencies and finite
32-packet output queues. Four diagnostic sinks accept one physical packet per
cycle without source-state, gather or Apply work. The resident R fixture only
initializes memory; it is not registered or executed, and a zero-write/global
read-ledger check rejects any hidden traffic from that fixture.

All four latency/registration cases pass. Every emitted weighted edge equals
the independent logical CSR, every physical slot and dummy lane is counted,
TLAST and requests/beats close, buffers remain bounded, and the two registration
orders agree exactly. Each scan reads **38,696,960 bytes in 3,803 requests**.
This includes the two source-0 dummy reservations inserted by admission;
the pre-admission census above is 128 bytes smaller. The complete service
peaked at 334,254,080 bytes with zero swap under its 4-GiB hard limit.

| Diagnostic | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| One physical scan, stall-free sinks | 526,038 | 949,472 |
| Same reader, 46 scans | 24,197,748 | 43,675,712 |
| Diagnostic floor / strong A4 complete result | 2.2191 | 2.7572 |

This is an **unchanged-reader diagnostic floor**, not an optimized R execution,
a causal partition of overlapping stalls, or hardware timing calibration.
Even without downstream backpressure the current reading path cannot meet the
10% target here. Merely optimizing the final drain or Apply is insufficient.
There is also a separate packet-rate constraint: worker 0 emits 359,016
physical eight-lane packets per scan, versus about 237,049 cycles per strong
A4 round at latency 64. A one-packet-per-cycle interface cannot recover the
target from read concurrency alone without also addressing padding delivery.

The separate [finite prefetch/compaction diagnostic](prefetch_compact/README.md)
now combines both changes, with actual reads, finite reservations, selection
and pipeline costs, weighted-edge/window conservation and backpressure tests.
Its four real-input executions and sixteen synthetic cases pass, but the
46-scan reader floor is still 1.789 / 1.256 times strong A4's complete result.
It is **not integrated R** and has not recovered the requested performance.
For that diagnostic, variable packet counts and termination still required
an explicit integrated contract; silently dropping dummy packets from the
fixed-count interface would be invalid. The diagnostic also isolates a
registered-arbiter issue interval; changing it for only G+R would not be a
valid control.

The separate [complete-convergence extension](prefetch_compact/CONVERGENCE.md)
now adds a default-off input owner and bounded TLAST framing to the actual
R composition. The default bank-stream results above are unchanged. Its
complete twelve-row matrix passes correctness/conservation and exactly
replays eight old rows. It improves that path by 12.2% / 39.6% but remains
2.591 / 2.197 times strong A4, failing the retention gate. It is not a
production-baseline admission, new Spine comparison or hardware result.

The first diagnostic attempt failed its independent CSR gate: it used the
pre-admission slot count instead of the runtime plan's normalized extent and
clipped three tail edges. Only the diagnostic consumer was corrected. That
attempt remains indexed alongside the four passing executions in the
[adapter-floor evidence capsule](evidence/adapter_floor_20261022_v2.json).

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-adapter-floor-NEW \
  -p MemoryMax=4G -p MemoryHigh=3G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=40min -p CPUAffinity=124 \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.adapter_floor \
  --output /data/chuxiao/experiments/r_bank_stream_comparison_20261022/adapter-floor-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --core-gates /data/chuxiao/experiments/sharded_k4_bank_stream_profile_20261019/gates-v1 \
  --cpu 124 --admission-wait-seconds 600

python3 -m unittest tests.test_regraph_adapter_floor tests.test_regraph_cached_core -q
```

### Complete Matrix

`spine_cycle_sim/experiments/evaluation_impact/r_bank_stream/` owns the study:
`study.py` builds and executes, `analysis.py` checks the complete matrix, and
`runtime.py` selects an explicit finite local or named high-memory policy. The C++
harness shares its configuration helper in `cpp/tests/evaluation_impact/`.
Production C++ and the SST plugin are unchanged; no plugin rebuild is needed
for this harness-only addition.

The build selects `/usr/bin/g++` explicitly, records its version and binary
hash, and verifies CMake actually selected that compiler. Both hosts report
GCC 15.2.0, although their Debian package revisions differ; exact replay is
still required rather than assumed from the version string.

The pre-edit freeze is
`/data/chuxiao/experiments/r_bank_stream_comparison_20261019/pre-edit/`.
It retains the pre-edit source archive, original 28-row report and independent
input/compiler/binary pins. The final source archive digest was checked before
editing. A relocated run must verify both frozen archives and every copied
input hash, not substitute a newly prepared graph.

```bash
python3 -m unittest tests.test_regraph_bank_stream_comparison tests.test_regraph_credit_controls -q
python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.study \
  --before /data/chuxiao/r_bank_stream_comparison_20261019/pre-edit \
  --inputs /data/chuxiao/r_bank_stream_comparison_20261019/inputs \
  --output /data/chuxiao/r_bank_stream_comparison_20261019/execution-NEW \
  --cpus 112 113 114 115
```

By default, the execution command requires an exact 40/36-GiB user cgroup, zero swap and
the named `seele-reserve-128g-v1` policy. It reserves full finite peer budgets,
uses a serial build and at most four isolated 4-GiB cases, and checks the live
128-GiB reserve throughout. The output must not already exist. `results.json`
retains complete observations, commands, failures and source/build/input pins;
`admission.json` and `live_memory.json` retain containment evidence. A running
or queued report is not a completed performance result.

The optional `--memory-profile local-finite-6g-v1` requires an exact
6/5-GiB max/high user cgroup, zero swap, group OOM kill and **one** CPU/worker.
It retains the same fresh Release build, complete 32-row matrix, numerical
configuration, 4-GiB child limit and exact 28-row replay. Only execution
admission changes: 24-GiB live reserve, 8-GiB background budget and every
competing compiler's full valid finite limit. Unknown or invalid peers still
reject admission; this is not the seele exception on a smaller machine.

Admission waiting defaults to 600 seconds and is bounded to 0--86,400 seconds.
`--admission-wait-seconds 0` samples once and starts work only if admitted.
Denied admission produces nonzero exit status and
`ADMISSION_NOT_GRANTED_NO_EXECUTION`, with no build steps or timing rows.
It is neither a performance failure nor a queued task that will later start.

For a fresh local attempt, retain the outer service limits:

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-bank-stream-local-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=24h -p CPUAffinity=126 \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.study \
  --before /data/chuxiao/experiments/r_bank_stream_comparison_20261019/pre-edit \
  --inputs /data/chuxiao/experiments/baseline_hardware_validation_20261015/r-credit-v2/inputs/warm_update \
  --output /data/chuxiao/experiments/r_bank_stream_comparison_20261022/local-NEW \
  --cpus 126 --memory-profile local-finite-6g-v1 --admission-wait-seconds 600
```

Choose an allowed CPU and unused unit/output names; do not overwrite an old
attempt. The remote default and existing immutable remote campaign are unchanged.

### Simulator-Only Checked-Core Execution

The user has deferred FPGA work. The optional
`cpu-only-cached-core-4g-v1` profile requires `--core-gates` pointing to a
completed passing core campaign. `cached_core.py` checks complete current
`cpp/src` and `cpp/include` coverage and hashes, both CMake source files,
and passing build/test records. The approved small experiment entry points are
freshly compiled in Release mode against those libraries. Library, compiler,
entry-point binary, input and current source hashes are pinned. The control
test and all seven focused C++ regressions still run before the same 32-row
matrix; all 28 historical results must still replay exactly.

This CPU-only profile requires exact 4/3-GiB max/high, zero own swap, group
OOM kill, at most four workers, an 8-GiB live reserve and a 4-GiB background
budget. Every competing compiler's full finite RAM limit remains reserved.
It permits nonzero *foreign* swap allowances only when `/proc/meminfo`
independently proves that the host has no configured swap. That condition is
rechecked during admission and by the live watchdog; unbounded or unknown
foreign RAM limits still reject admission. Other profiles retain their
stricter foreign-swap checks. No foreign process or limit is changed.

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-cpu-core-NEW \
  -p MemoryMax=4G -p MemoryHigh=3G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=4h -p CPUAffinity='124 125 126 127' \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.study \
  --before /data/chuxiao/experiments/r_bank_stream_comparison_20261019/pre-edit \
  --inputs /data/chuxiao/experiments/baseline_hardware_validation_20261015/r-credit-v2/inputs/warm_update \
  --output /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-NEW \
  --cpus 124 125 126 127 --memory-profile cpu-only-cached-core-4g-v1 \
  --core-gates /data/chuxiao/experiments/sharded_k4_bank_stream_profile_20261019/gates-v1 \
  --admission-wait-seconds 0
```

The observed CPU-only admission reserved both foreign 32-GiB compiler caps
plus 4 + 8 + 4 GiB: 80 GiB total, against 87.21 GiB available. The 4-GiB
physical cap applies to the complete owned process tree, not four separate
4-GiB allocations. This is neither a fresh complete-core rebuild nor FPGA
timing admission. Raw failed and replacement attempts stay separate under
`cpu-core-matrix-v1/` and `cpu-core-matrix-v2/`.
The completed replacement peaked at 1,199,673,344 bytes (1.12 GiB) for the
whole owned cgroup with zero swap. This observed peak does not replace the
4-GiB hard budget in future admission decisions.

## Remote Attempt

Remote root: `/data/chuxiao/r_bank_stream_comparison_20261019/`.
The immutable `campaign-v2/` transfer contains 2,332 independently checked
files; its archive SHA-256 is
`6823ff0f86c930041efb3877dff258b30be4fcd53d276942a52418d1953e0548`.
It runs as `spine-r-bank-stream-convergence-20261019-v2.service`, invocation
`124f9d284db14be39fef1203a8c1a0ad`, with output `execution-v2/`.
Temporary files use the existing campaign-specific `campaign-v2/tmp/`.

The preceding immutable `execution-v1/` is retained as `FAILED_RETAINED`.
CMake selected an environment-provided Clang, which rejected existing
GraSU override warnings under `-Werror`; its requested temporary directory
was also absent. No matrix row ran and no timing result was obtained. The
replacement pins GCC and an existing temporary directory; it does not change
GraSU source, suppress warnings, or overwrite the failed attempt.

## Local Admission Checkpoint

The [admission record](evidence/local_admission_20261022_v1.json) indexes the
raw `local-admission-v1/` report under
`/data/chuxiao/experiments/r_bank_stream_comparison_20261022/`.
Available memory was 53.734 GiB. Two foreign compiler cgroups each had a
32-GiB hard cap but nonzero swap allowances, which the strict policy rejects.
Even if those peers satisfied the swap rule, their full budgets plus this
study's 6 + 24 + 8 GiB would require 102 GiB. No foreign limit was changed.
No build step, matrix row or new performance claim resulted.

Fifty focused policy, analysis, credit-control and repository-structure tests
passed under a separate 2-GiB/zero-swap scope. They validate execution and
acceptance logic, not the new topology's cycle prediction. C++/SST numerical
owners, HLS, paper and frozen figure packages were not changed this checkpoint.
