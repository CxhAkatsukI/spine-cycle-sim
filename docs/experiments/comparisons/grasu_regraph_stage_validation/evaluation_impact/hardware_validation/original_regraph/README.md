# Original ReGraph Hardware Controls

## Decision

`original-r-preflight-v2` completes the fixed six-input **offline** audit.
The portable [evidence index](evidence/index.json) seals the raw observations,
metadata, reviewed author source files, audited runner and retained failures.
It is not FPGA execution, a timing calibration or a publication-speed match.
No board was programmed by this study. The complete-new-G route and its
conditional board queue can run concurrently with this independent work.

| Question | Result | Still required |
| --- | --- | --- |
| Do captured author tasks preserve the CSR gather? | Yes, all six inputs | Device output and timing |
| Does the original host upload CSR degree to the PR apply divisor? | No; the reviewed revision uploads initial vertex properties | Explicit binding controls, not a silently corrected author baseline |
| Does the original aligned output allocation cover mixed publication? | Not for boundary-ring and Amazon | Declared safe allocation control before a board launch |
| What is the prebuilt's DATA clock? | Metadata says 215 MHz, not its requested 230 MHz | Checkpoint, timing-clock and bitstream identity pairing |
| Is the 11-Little/3-Big prebuilt admitted? | No | Source/ABI identity, clock/timing and guarded board validation |
| Is this the paper's graph-selected best configuration? | Not established | Original publication platform, topology, window and denominator |
| Is the guarded host implemented and validated? | Yes, compilation and 48 offline runs | Admitted artifact and actual board execution |

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

1. Bind a clean author device/ABI identity to an admitted implemented clock,
   or route a freshly frozen original-R candidate; keep A4 separate from A.
2. Execute the now-implemented guarded fixed-BDF host against an admitted
   artifact. Its offline checks do not validate DMA, device execution or
   the board ABI. Keep the two divisor controls separately labeled.
3. Validate its complete resident compute span and per-kernel event records
   on the board, not only the author's late timer or a sum of overlapping
   lanes. Host preparation remains separate; use declared repeats and
   retain every failure.
4. Only then compare original R, resource-disclosed A4 and actual adapter/K4;
   publication reproduction and Spine speedup remain later, separate gates.

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
implements the reviewed original 11-Little/3-Big ABI. It uses a fixed U55C BDF,
requires an external exclusive board lease, explicitly names the apply-divisor
binding, repairs unsafe output allocation, and checks every output replica,
publication padding, unused tail and guard. It also checks that source,
divisor and edge inputs remain unchanged. A4 is supported for offline layout
checks, but its unimplemented board ABI is rejected before device programming.

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
