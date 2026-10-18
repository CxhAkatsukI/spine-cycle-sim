# Original ReGraph Hardware Controls

The [actual adapter/K4 control](k4_control/README.md) tracks the separate
production-layout semantic and eventual board comparison against original A4.
It does not replace original 11+3 or A4 evidence below.

## Decision

`original-r-preflight-v2` completes the fixed six-input **offline** audit.
The portable [evidence index](evidence/index.json) seals the raw observations,
metadata, reviewed author source files, audited runner and retained failures.
It is not FPGA execution, a timing calibration or a publication-speed match.
No board was programmed by that offline audit. The subsequent
[guarded board matrix](board_matrix/README.md) passes all eighteen actual
11-Little/3-Big runs at 150 MHz, including independent output and timing
checks. It is a static one-superstep same-platform control, **not** a paper
performance reproduction or convergence comparison. A4's distinct placement
retry and board v3 also pass all eighteen declared runs; the actual adapter/K4
same-semantic comparison remains open. The diagnostic G route is not the
production-G candidate. See the campaign's [current checkpoint](../README.md)
for production routing rather than the historical queue records below.

The separate [arithmetic-control audit](arithmetic_control/README.md) defines
the original fixed-point versus candidate K4 binary32 payload boundary before
that pending adapter/K4 comparison. It does not alter either production default
or admit measured performance.

| Question | Result | Still required |
| --- | --- | --- |
| Do captured author tasks preserve the CSR gather? | Yes, all six inputs | Device output and timing |
| Does the original host upload CSR degree to the PR apply divisor? | No; the reviewed revision uploads initial vertex properties | Explicit binding controls, not a silently corrected author baseline |
| Does the original aligned output allocation cover mixed publication? | Not for boundary-ring and Amazon | Declared safe allocation control before a board launch |
| What is the prebuilt's DATA clock? | Metadata says 215 MHz, not its requested 230 MHz | Checkpoint, timing-clock and bitstream identity pairing |
| Is the 11-Little/3-Big prebuilt admitted? | No | Source/ABI identity, clock/timing and guarded board validation |
| Is this the paper's graph-selected best configuration? | Not established | Original publication platform, topology, window and denominator |
| Is the guarded host implemented and validated? | Exact Xilinx-linked hosts pass offline validation; 11+3 and A4 each pass their distinct eighteen-row board matrix | Actual adapter/K4 same-semantic comparison |

The allocation finding was already reported by the earlier
[mixed source control](../../../MIXED_GRAPH_EXECUTION.md). This checkpoint
rechecks it against frozen inputs; it does not invalidate that explicitly
padded source experiment or imply a new PMA/K4 performance result.

## Fixed Inputs And Results

Both the four-Little control (`a4`) and the author's 11-Little/3-Big example
(`original_example`) use boundary-ring, skewed-source and Amazon inputs from
the admitted [original-host matrix](../../../input_results.json). Each input
already has two identical captured layouts. This study rechecks the first
capture's seven binary files, CSR degrees, source/task bounds, padding,
independent CSR/task gather equality and fixed-point arithmetic. It does not
rerun the author input generator or claim a new repetition of those captures.

| Configuration / input | Different apply divisors | Different logical output vertices | Publication beyond original allocation, 32-bit words |
| --- | ---: | ---: | ---: |
| A4 / boundary-ring | 131,073 | 131,073 | 0 |
| A4 / skewed-source | 4,097 | 4,096 | 0 |
| A4 / Amazon | 646,766 | 646,766 | 0 |
| 11+3 / boundary-ring | 131,073 | 131,073 | 393,216 |
| 11+3 / skewed-source | 4,097 | 4,096 | 0 |
| 11+3 / Amazon | 646,766 | 646,766 | 327,680 |

All six independent gathers match; neither tested apply binding overflows
signed arithmetic. These are **one static fixed-point PR superstep with
`arg=0`**, not residual PR, SSSP or convergence. The two explicit apply
bindings are initial-property-as-divisor (the reviewed original host) and
CSR-outdegree-as-divisor (a semantic control). They produce the same outputs
across A4 and 11+3 for a given graph, but differ from one another as shown.
No binding is silently substituted, and no publication-algorithm claim follows.

Amazon retains original integer IDs including unused ID zero: 735,324
vertices, 5,158,388 logical edges and 5,165,928 physical task entries. Its
source file SHA-256 is
`60b383901873b49883d0c67d8b524244ada1977719d25c834014b75238f3a815`.
Boundary-ring has 131,073 vertices / 131,137 edges; skewed-source has
65,537 vertices / 8,193 edges. No compacted vertex-ID input is substituted.

## Host And Artifact Findings

The clean author revision is
`365456826cef495285383d939907f847e05ad74b`. The capsule records exact file
hashes and unique literal review anchors, not a generic C++ analysis:

- `partition_schedule.cpp` binds the apply buffer to `vertex_property`, not
  the captured CSR degree array; `host.cpp` passes that buffer to apply.
- The author host runs one superstep. Its wall timer starts after task
  enqueues, so it is not a full host-inclusive resident compute timer.
- The host ignores the verifier's return value, and that verifier returns
  one unconditionally. Exit zero alone cannot admit correctness.
- The original device-selection loop tries devices until programming works;
  it is not our required exclusive, fixed-BDF board lease.
- Mixed publication emits `(dense_partitions + 8*sparse_groups)*65536`
  words. The original aligned vertex allocation can be shorter. No padding
  correction or FPGA launch was performed by this offline audit.

The prebuilt is
`/data/feiyang/AE/AE/Regraph_good/prebuilt_230mhz/ReGraph_pr_230Mhz/xclbin_hw_pr/graph_fpga.hw..xclbin`.
Extracted metadata identifies eleven Little CUs, three Big CUs, two mergers,
apply and the HBM wrapper, with DATA 215 MHz, KERNEL 500 MHz and HBM 450 MHz.
Its apply divisor uses HBM bank 30; our K4 host's bank-below-23 guard is not
an original-R-compatible allocator and must not be reused unchanged.

The saved requested-230-MHz report has WNS -0.343 ns, TNS -1133.961 ns and
12,083 failing setup endpoints; hold and pulse-width checks pass. The adjacent
`v++_graph_fpga.hw..log`, line 387, records automatic frequency reduction to
215.1 MHz. Therefore the old negative slack is **not proof of timing failure
at the reduced clock**, but metadata alone is also not a timing admission.
Pair the relevant checkpoint/constraints and implemented artifact before
programming. The source/prebuilt equivalence is separately unverified.

## Reproduce And Verify

Code ownership is in
[original_regraph_execution/hardware](../../../../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/README.md).
From the simulator worktree root, use a fresh output directory:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.study \
  --inputs docs/experiments/comparisons/grasu_regraph_stage_validation/input_results.json \
  --upstream /path/to/clean/pinned/regraph \
  --prebuilt /path/to/ReGraph_pr_230Mhz \
  --output /path/to/fresh/offline-audit
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.original_regraph_execution.hardware.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/original_regraph/evidence"))'
```

The external raw campaign root is
`/data/chuxiao/experiments/baseline_hardware_validation_20261015`.
The successful audit ran in a 2-GiB hard / 1,792-MiB high / zero-swap scope,
CPU 123, with a 104-GiB reserve and 600-second outer timeout. It completed
in 8.667 seconds, maximum-process RSS 202,056 KiB; extraction has a separate
120-second timeout. The full raw recheck and package took 8.964 seconds,
202,100 KiB. These are CPU audit costs, not accelerator measurements.
Large captured inputs, the xclbin and external tool binaries are indexed by
hash rather than duplicated into Git. The packaging code is delivered in
this repository; the archived runner identities refer to the actual audit.

Thirteen focused tests pass, including changed captures, symlinks, overflow,
source-anchor changes, invalid clocks/topologies, promoted hardware claims,
missing rows and archive tampering. The capsule retains the failed v1 XRT
extraction (`SYSTEM_METADATA:JSON` is unsupported; v2 uses `RAW`) and the v3
test-fixture failure (a reused mutable mock result), followed by passing v4
tests. No numerical acceptance threshold was relaxed. A rejected systemd
property before process launch produced no audit result; it is not a run.
The broader original-ReGraph regression passes 133 tests and the repository
organization suite passes 15; their external bounded logs are in
`verification-original-r-regressions-v1/`. Document-layout, generated-catalog
and whitespace checks also pass. No SST rebuild, FPGA measurement or full
repository test suite is claimed by this offline checkpoint.

## Next Hardware Gates

1. Preserve the completed fresh 150-MHz 11+3 artifact, eighteen raw board
   rows and explicit divisor controls. The older prebuilt remains unadmitted.
2. Preserve A4's distinct admitted placement retry and completed eighteen-row
   board v3 matrix; 11+3 success alone does not authorize A4 or replace its
   strict timing checks.
3. Compare original R, resource-disclosed A4 and actual adapter/K4 with
   matching inputs, semantics and resident windows. Keep overlapping device
   event spans separate from host enqueue-to-completion wall time.
4. Establish the original publication's platform/configuration/window and
   denominator before claiming a paper-speed match. Dynamic convergence,
   host-inclusive G+R and Spine speedup remain separate later gates.

## Independent Read-Only Checkpoint Probe

`original-r-checkpoint-v1` opens the author's saved
`level0_wrapper_postroute_physopt.dcp` without changing constraints, routing,
or writing an implementation/bitstream. It extracts the xclbin's embedded
partial bitstream for an exact comparison with the adjacent saved partial.
Native checkpoint timing, recorded auto-scaled clock, and actual board timing
are different observations. A matching partial file does not prove which DCP
produced it; neither that match nor a successful query admits FPGA execution.

The probe runs independently of the new-G route. Its atomic admission records
138.551 GiB available against 92 GiB required: 20 GiB for this query, the
concurrent route's full 40-GiB limit, a 24-GiB system reserve and an 8-GiB
background allowance. It does not wait for unrelated FPGA tools to exit when
their bounded budgets fit. Unbounded peers or insufficient memory prevent a
launch. Both tasks retain their own cgroups, watchdogs and temporary directories.

The query uses Vivado 2024.1, a 20-GiB hard / 18-GiB high / zero-swap service,
group OOM handling, CPUs 124--125 and a 1,200-second process-tree timeout.
The service has a separate 1,800-second lifetime. It freezes checkpoint,
partial, xclbin, prior audit, environment, tool and transitive runner hashes;
large vendor artifacts are indexed rather than copied into Git.

To reproduce, run from the worktree root with fresh unit/output names. The
captured environment must be the reviewed, license-free Vivado environment,
not arbitrary shell settings:

```bash
systemd-run --user --unit=original-r-checkpoint-fresh \
  -p MemoryMax=20G -p MemoryHigh=18G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p CPUQuota=200% -p AllowedCPUs=124-125 -p RuntimeMaxSec=1800 \
  -p TimeoutStopSec=30 -p KillMode=control-group -p TasksMax=512 \
  --working-directory="$PWD" \
  /usr/bin/python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.checkpoint_run \
  --prebuilt /path/to/ReGraph_pr_230Mhz \
  --audit /path/to/successful/offline-audit \
  --environment /path/to/reviewed/environment.json \
  --output /path/to/fresh/checkpoint-query
```

The probe does not repair the author's host allocation/divisor behavior or
replace A4 with the prebuilt 11+3 topology. Those remain explicit subsequent
controls. No simulator timing parameter or paper figure changes here.

The read-only query completed in 890.677 seconds, with sampled process-tree
peak RSS 15,547,284 KiB and minimum available memory 121.911 GiB. All cgroup
memory-event counters remained zero. The native checkpoint constrains DATA
to 4.348 ns (about 229.991 MHz), not the xclbin's reduced 215-MHz clock.
Native setup timing fails: WNS -0.299 ns, TNS -1104.576 ns and 11,993 failing
endpoints. Hold passes (WHS +0.001 ns, zero failing endpoints); pulse-width
checks pass. All 1,072,202 routable nets are fully routed, with zero reported
routing errors.

The embedded partial bitstream exactly matches the adjacent saved partial.
That does not prove DCP/bitstream pairing or clean-source equivalence. Native
230-MHz failure also does not prove failure at the recorded reduced clock.
Timing at that clock remains unverified, so the prebuilt is still **not
admitted for board execution**.

The [checkpoint capsule](checkpoint_evidence/index.json) contains the raw
query reports, logs, runner and reference metadata. Large vendor artifacts
are hash-indexed externally. The first packaging attempt rejected the roughly
32-MiB full timing report under a 16-MiB log-size cap. The successful retry
uses a tested 64-MiB cap for that report only; timing criteria and frozen query
results are unchanged. Its archive SHA-256 is
`8f3225429f310e3804d2470e2025cea7e1f636f1be0a35bc78899d345089e9cd`.

The earlier checkpoint regression passed 144 original-ReGraph tests and 15
organization tests in `verification-original-r-checkpoint-v2/`. An unsupported
`MemoryOOMGroup` scope property was rejected before that regression launched;
the retry used a 2-GiB hard / zero-swap scope. That rejection is not an FPGA
result. No simulator parameter or figure changed.

## Guarded Host: Compiled And Offline-Validated

The [C++ control owner](../../../../../../../cpp/tests/original_regraph/hardware/README.md)
originally implemented the reviewed original 11-Little/3-Big ABI. It uses a fixed U55C BDF,
requires an external exclusive board lease, explicitly names the apply-divisor
binding, repairs unsafe output allocation, and checks every output replica,
publication padding, unused tail and guard. It also checks that source,
divisor and edge inputs remain unchanged. A4 is supported for offline layout
checks in that historical binary, whose unsupported board ABI is rejected
before device programming. The new separately validated A4 host is described
below; it does not rewrite or upgrade this frozen evidence.

The timer starts before argument binding and the first kernel enqueue and
stops after all kernels complete. Raw profiling events permit both an
overlap-aware union and the complete event span. Programming, preparation,
DMA and readback are outside that resident-compute window; this is not a
host-inclusive or convergence measurement. These are implemented measurement
paths, not timings already obtained from a board.

`original-r-control-validation-v4` passed all 48 offline runs:

- Two layouts: A4 and the author's 11-Little/3-Big example.
- Three graphs: boundary-ring, skewed-source and Amazon, without ID compaction.
- Two explicit divisor bindings: `author_initial` and `csr_degree`.
- Two repetitions each, in both Release and UBSan builds.

Each output matches the independently frozen CSR/task oracle. Repeat/build
hashes match, and both layouts produce the same logical result for each
binding. Guarded full outputs are retained separately from canonical logical
hashes. Missing board lease, unknown binding, unsupported A4 board ABI and
symlinked input all fail for the expected reason. Offline mode does not
enumerate or program a device.

The bounded service completed in 24.504 seconds with a 325.7-MiB cgroup peak,
4-GiB hard / 3,584-MiB high / zero-swap limits and CPU 123. Admission recorded
136.506 GiB available against 76 GiB required, including the concurrent G
route's full 40-GiB budget, a 24-GiB reserve and an 8-GiB background allowance.
All cgroup memory-event counters remained zero.

The [control capsule](control_evidence/index.json) packages raw per-case JSON,
logs, resource records and reviewed sources. Large inputs, complete binary
oracle outputs, tool binaries and compiled hosts are hash-indexed rather than
duplicated into Git. It retains the three rejected attempts: compiler symlink
identity (v1), use of an older simulator source gate (v2), and passing a raw
directory instead of the exact audited report (v3). The final control consumes
the exact report and captures pinned by the independent audit; it does not
relax that older gate or rewrite historical evidence.

The expanded original-ReGraph regression passes 153 tests; 15 organization
tests and the document-layout check also pass. Raw bounded logs are in
`verification-original-r-control-v1/`. Its initial whitespace check failed
because Git could not create index-preload threads under the process address
space limit; a retry disables that optional Git optimization. This is a test
runner resource issue, not a device or numerical failure. The bounded retry
in `verification-original-r-control-v2/` passes all 153 original-ReGraph tests,
15 organization tests, document layout, catalog generation/checking and both
working-tree and staged whitespace checks. No numerical simulator component
changed, so this checkpoint does not claim a new SST build or calibration.

**Remaining:** artifact/source/clock admission, actual original-R and A4 board
execution, comparison with the actual adapter/K4 path, publication-speed
reproduction and the later Spine matrix. No new FPGA speedup, simulator
calibration or Fig. 7--11 result is claimed by these offline controls.

## Fresh Source Build

The builder now also accepts explicit `--topology a4`, using the author's
generator with four Little and zero Big pipelines. The default 11+3 compile
commands, macros and ABI remain unchanged. A4 needs four unique XOs and seven
implemented CUs, not the mixed control's six XOs and eighteen CUs. Its separate
routed status prevents a 11+3-only host from authorizing it.
Matching four lanes does not match every K4 resource: A4 retains the author's
nine used HBM banks rather than our integrated 23-channel layout.

`a4-source-preflight-v1` in the campaign root exercises the actual clean
author revision `365456826cef495285383d939907f847e05ad74b` with Python 3.11.2.
Only the six permitted generated outputs change; device algorithm source
does not. The service completed in 812 ms with a 22-MiB peak and zero memory
limit/OOM events under a 2-GiB/no-swap limit. This first preflight explicitly
records the dirty development worktree and frozen source hashes; it is not
a clean-commit hardware build or a board measurement. Thirty focused source,
queue and A4 tests pass, including cross-topology ABI rejection and memory
failure controls. Actual compiled ABI, routing, an A4-capable board host,
correctness and performance remain open.

The full original-ReGraph regression passes 200 tests, with 15 organization
tests, documentation-layout/catalog checks and whitespace checks also passing.
Bounded logs are in `verification-a4-source-v1/` under the campaign root;
the ReGraph test service peaks at 46.5 MiB. An independent comparison to
revision `839bd66` confirms exact default compile/link commands, argument
order and control protocol for all six 11+3 kernels. No numerical simulator
model, frozen running build or paper figure changes in this revision.

The repeated `a4-source-preflight-v2` uses clean simulator commit `9dcab0d`
and the same pinned author revision/generator. It passes in 809 ms with a
23-MiB peak. Source queue `spine-a4-source-route-20261016-v1.service`, invocation
`2dd055963c9544ddb85b4e8e5b1dc38f`, freezes that worktree separately from
the running G and 11+3 builds. It has 40-GiB hard / 36-GiB high / zero-swap
limits, CPUs 112--115 and an eighteen-hour bounded admission wait. At
2026-10-16 02:36 UTC it has launched no compiler: approximately 85 GiB is
available against 152 GiB required for the known full budgets plus reserve;
other peers also fail the zero-swap bounded-build rule. This is memory
admission, not a requirement that all other FPGA tools exit.

That A4 run subsequently completed all four XO builds and generated an xclbin,
then failed its frozen analysis because the old checker incorrectly counted
AXIS connections as HBM bindings. A separate read-only check now distinguishes
the nine HBM banks from fourteen named AXIS endpoint pairs; both binding checks
pass without modifying the artifact or the frozen run. **Final global timing
still fails:** HBM setup WNS is -0.098 ns, TNS -3.846 ns, with 79 failing
endpoints; kernel-clock WNS alone is +0.889 ns. The authoritative report is
`a4-source-route-v1/build/link/reports/link/imp/impl_1_hw_bb_locked_timing_summary_routed.rpt`.
The existing board supervisor stopped before programming. This is not an
admitted A4 bitstream or a measured comparison; fixing the metadata checker
does not waive physical timing. The original failure record is retained.

The failing HBM response path is `hmss_0/inst/path_28/slice1_28/...dual_slr.resp`.
The generated block-design interface maps bind path 28's `S01_AXI` to
`kernelApply_1/m_axi_gmem2`, assigned to HBM[30]. This makes Apply's SLR1-to-SLR0
memory crossing a concrete placement candidate, not proof that a move will
close timing. The new opt-in `--topology a4 --placement apply_slr0` changes
only `slr=kernelApply_1:SLR1` to `slr=kernelApply_1:SLR0` in a separate pinned
connectivity file. The author snapshot, four Little placements, HBM banks,
fourteen streams, clocks, algorithm macros and strict timing checks stay
unchanged. Missing, duplicate or drifted author placement is rejected before
build admission. This is a same-platform physical control, not the author's
original placement or a publication reproduction. A fresh output and frozen
worktree are required; the failed artifact is not modified or board-admitted.

The placement/default-command/queue regression and all original-R tests pass
218 tests in 1.024 seconds in a 1-GiB, zero-swap service (44.1-MiB peak).
Fifteen organization tests and both documentation/catalog checks also pass.
These are software regressions, not evidence of a successful route or board
comparison. No numerical simulator model or paper figure changes here.

The independent `codex/regraph-a4-board-control` worktree adds the actual
four-lane host path without changing either frozen running builder. The
board owner explicitly selects `a4` across the source manifest, four XO ABIs,
routed artifact, input descriptors, child reports and all four output replicas.
Legacy hosts remain admissible only for their historical 11+3 path. A4 needs
a fresh 48-run Release/UBSan validation with both lease-negative controls;
then its own eighteen-row matrix is independently rechecked. The Python
regression passes 209 original-R tests in 1.016 seconds with a 46.6-MiB peak,
including both topology paths, every A4 output guard, cross-topology rejection
and admission while peers are running. These are unit tests with mocked board
operations, not actual FPGA observations. Fresh C++ compilation, routing,
board correctness/timing, publication matching and Spine comparisons remain
open. No numerical simulator core or paper figure changes in this checkpoint.

The separate [source-build owner](../../../../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/source_build/README.md)
compiles the clean pinned author revision after invoking only its topology
generator for 11 Little and 3 Big pipelines. This is a U55C, 150-MHz
same-platform control, not a reproduction of the publication's original
clock or graph-selected best configuration. No device algorithm edits or
simulator timing changes are included.

It requires the passing six-input audit and 48-run offline guarded-host
validation, freezes all source/tool/environment identities, and separately
checks the six XO ABIs, HLS target, eighteen implemented CUs, author HBM
mapping, actual DATA clock and strict setup/hold/pulse timing. The mergers
are free-running stream-only kernels; the remaining kernels use the author's
chain-control ABI. XRT's `MEM_DRAM` representation of some U55C HBM banks is
accepted only with the pinned U55C platform, correct HBM tags, enabled banks
and 512-MiB capacity.

Other FPGA tools do not block this build when their **full finite budgets**
fit. The independent service uses a 40-GiB hard / 36-GiB high / zero-swap
cgroup; admission adds every peer's full limit, a 24-GiB reserve and 8-GiB
background allowance. The live watchdog retains 32 GiB available. Its six
XO compilations are sequential within that budget; G routing can continue
concurrently. Insufficient memory or unbounded peers prevent tools launching,
without an unconditional wait for those tools to exit.

Each fresh run retains its source snapshot, commands, compiler logs,
resource records and failure observations under the external campaign root.
Successful routing still requires guarded board correctness and measurements;
neither a running build nor an emitted xclbin is a performance-match result.

The source-build regression passes 164 original-ReGraph tests (including
11 new build-specific checks) and 15 repository-organization tests. Document
layout, catalog and staged/unstaged whitespace checks pass. Raw bounded logs
are in `verification-original-r-source-v1/` under the campaign root. Source
snapshot tests reject algorithm edits, unexpected generated files and drift
in the clean upstream checkout. Interface, macro, clock, bank-capacity,
timing and insufficient-memory negative controls also pass. This checkpoint
changes no numerical simulator component and claims no SST rebuild or board
performance result.

The first source-build launch, `original-r-source-route-v1`, was memory-admitted
with 133.681 GiB available against 112 GiB required, including the concurrent
G route's full 40-GiB limit. It stopped in the author's Python generator,
before any FPGA compiler launch: system Python 3.13 no longer exports the
unused `re.T` import. Its raw logs and zero-OOM memory events remain intact.
The runner now explicitly pins Python 3.11, the interpreter used by the
earlier original-source controls; author algorithm and generator sources
are unchanged. A retry uses a new unit and output directory.

The second attempt, `original-r-source-route-v2`, passed that generator and
launched HLS, but stopped at C++ analysis because the current header environment
does not define the author's legacy `uint` type. It was memory-admitted with
133.537 GiB available against 112 GiB required, reached a 681.7-MiB cgroup
peak, and recorded zero high/max/OOM events. This is a compiler-compatibility
failure, not a placement, routing, correctness or performance result.

The next attempt supplies a four-byte `unsigned int` alias in separate,
hash-pinned entry translation units, then includes unchanged author source.
No algorithm, pipeline, port, timing threshold or upstream file is modified.
The regression checks the exact entry text, author-source identities, normal
C++ type compilation and rejection of entry drift.

At the next launch checkpoint, `original-r-source-route-v3` was independently
admitted with 133.491 GiB available against 112 GiB required, including the
still-running G build's full 40-GiB budget. Its own limits are 40-GiB hard,
36-GiB high, zero swap, four CPU equivalents, explicit CPU affinity 120--123
and a ten-hour service lifetime. The Apply compiler passed the previously
failing source-analysis step. Both concurrent services had zero high/max/OOM
events at inspection. This records a running build, not completed routing or
hardware admission; terminal status and logs belong to that raw run.

The compatibility regression in `verification-original-r-source-v3/` passes
165 original-ReGraph tests, 15 organization tests, document-layout/catalog
checks and whitespace checks. The bounded check service used a 2-GiB hard
limit, zero swap and a 52.8-MiB peak. No simulator numerical code, paper or
figure data changed.

That v3 launch subsequently stopped at HLS interface checking: Apply's
implicit `arg_reg` was placed into the new tool's default `control_r` bundle,
conflicting with the author's explicit `control` bundle. The source-analysis
pass did not mean completed synthesis. Its retained logs report error
`HLS 214-219`; the 25.364-second compiler run produced no admitted XO and
recorded no memory-limit/OOM events. A separately pinned pre-synthesis Tcl
directive now explicitly binds that argument to `control`. The author
translation unit remains unchanged; no arithmetic, stream, data-memory port,
schedule or timing threshold is adjusted. The next attempt uses a fresh
output directory again.

Attempt `original-r-source-route-v4` was admitted with 133.418 GiB available
against the same 112-GiB requirement while G remained active. It freezes
revision `c8e6ebc` and the explicit Apply control-bundle directive. The v4
bounded verification logs retain all 165 original-ReGraph and 15 organization
test passes plus document, catalog and staged-whitespace passes. This launch
is not a completed routing or board result.

Attempt v4 subsequently compiled Apply, HBM wrapper, Little scatter/gather,
Little merger and Big scatter/gather successfully. It stopped before the sixth
compiler or routing because the Big XO's legitimate 1,331,082-byte kernel XML
exceeded the checker's uniform 1-MiB size cap. This is a parser-bound failure,
not an HLS, correctness or timing failure. Its peak was 2,601,603,072 bytes;
raw outputs remain untouched. Only Big scatter/gather now has a tested 4-MiB
metadata cap; all other kernels retain 1 MiB, and numerical/ABI/timing criteria
are unchanged. A fresh output directory is required for the next attempt.

The new [board-execution owner](../../../../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/board_execution/README.md)
supports an exact-invocation conditional queue and independent route readmission
before exclusive fixed-BDF board execution. Its predeclared matrix is three
graphs x two explicit divisor bindings x three repetitions = eighteen runs.
It checks all fourteen output replicas and independent oracles, records the
resident wall window and overlap-aware event union/span, and retains failures
without reset/retry. It is one static fixed-point PR superstep, not convergence,
host-inclusive latency or a publication-speed match. Implemented queue support
does not mean the board matrix has already passed.

The bounded verification in `verification-original-r-board-v5/` passes all
183 original-ReGraph tests and 15 organization tests, plus document-layout,
catalog and whitespace checks. Its 2-GiB hard / zero-swap service peaked at
55.4 MiB. New tests exercise all output replicas, event overlap and malformed
timestamps, exact service identity, resource rejection, source drift, exclusive
lease-FD forwarding, worker timeout and complete raw-result rechecks. These are
offline tests with mocked board launches, not eighteen actual FPGA results.
An additional read-only check of v4's real Big XO now passes the unchanged ABI,
macro, control-protocol and HLS-target checks with the corrected finite size cap.
The retained v4 memory-event counters are all zero. No simulator numerical
component, paper or figure result changed.

Attempt `original-r-source-route-v5` was refused before any compiler launch:
available memory fell to 108.842 GiB, below the 112-GiB requirement including
G's full budget, and newly observed peer processes did not pass the finite
zero-swap ancestry check. Its retained failed result is a safety decision, not
a hardware failure. The already admitted G build continued into routing.

The optional source-build memory queue now polls the same atomic budget check
every ten seconds, with a finite deadline and unchanged safety thresholds. It
does not wait for all FPGA tools to exit. Waiting holds neither a compiler
reservation nor a board lease; compiler launch has its own second admission.
The queue freezes its prerequisites, runner and environment, stops on drift,
and does not retry a failed real build. Its `queue.json` is distinct from the
nested `build/results.json`; neither waiting nor offline tests are board data.

The subsequent read-only peer inspection found a 48-GiB Podman hard limit,
zero swap at the leaf and a nonzero swap allowance at its bounded ancestor.
The existing strict ancestry check rejects that configuration; this is not
proof of unlimited actual RAM use. Even counting it as a finite 48-GiB peer,
G (40 GiB) + R (40 GiB) + that peer (48 GiB) + reserve/background (32 GiB)
would require 160 GiB under this campaign's conservative full-budget rule,
against approximately 119 GiB then available. No peer configuration or live
G-pinned admission module was changed to force acceptance.

The memory-queue regression passes six new tests and all 189 original-R tests,
plus fifteen organization checks and document/catalog/whitespace checks. The
bounded full regression service peaked at 43.9 MiB under its 2-GiB hard limit.
These tests validate queue/admission behavior, not hardware performance.

Attempt `original-r-source-route-v6` then passed its first memory sample:
133.617 GiB available against 112 GiB required, with G still routing and no
unbounded peers at that sample. The compiler's independent second admission
also passed at 133.589 GiB, and Apply compilation actually started. This
demonstrates concurrent launch by budget, not waiting for G to exit.
The exact source service is `spine-original-r-source-route-20261016-v6.service`,
invocation `34a2442a7f2b4bce88f0596120d93e73`, with the same 40/36-GiB hard/high
and zero-swap limits. Its queue file is at the attempt root; source-build
manifest/results/logs are nested under `build/` and freeze revision `b9508ae`.

`original-r-board-supervisor-v1` is also running with an 8/7-GiB hard/high,
zero-swap limit, waiting for that exact source invocation. It targets device 1
and all eighteen predeclared static-PR controls; G's independent board queue
targets device 0. The `Requisite` dependency retains the source unit's terminal
identity without restarting it. No R board launch has occurred at this
checkpoint, and there is still no new measured R performance or publication
match. G route and G-board frozen content hashes remain unchanged.
