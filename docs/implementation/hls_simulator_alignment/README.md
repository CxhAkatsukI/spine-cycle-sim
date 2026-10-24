# Simulator-To-HLS Source Handoff

## Status

This is the 2026-10-24 source delivery after the scheduled machine reboot.
The reboot deadline no longer applies. No synthesis, routing, FPGA execution,
new calibration, figure replacement, or manuscript edit was performed here.

**The source candidates and bounded functional checks are delivered; complete
simulator/HLS architecture and timing alignment is not established.** In
particular, the new complete G+R topology exceeds the current platform's AXI
master admission budget. It is not ready for an unconditional full-system build.

## Reading Order

1. This page: source ownership, what changed, and unresolved gates.
2. [Validation](VALIDATION.md): exact checks, commands, limitations and failures.
3. [Source identities](sources.json): pinned simulator and two HLS commits.
4. [Evidence index](evidence/README.md): small raw logs and generated input hashes.

The simulator repository owns this index, not copies of production HLS code.
The two HLS branches are both named `codex/simulator-aligned-hls-20261024`.
Check out those branches, not an older routed worktree with a similar pathname.

| Repository | Pinned source | Implementation guide |
| --- | --- | --- |
| Simulator | `567a37a406dddea8917cbdc8ba8c59d8cee87198` | [G+R input profile](../grasu_regraph/README.md), [Spine selector](../spine/residual_sparse_apply.md) |
| Spine HLS | `c5fb7a7df41d1496f2aebede99595bea4a2d42b9` | [Sparse Apply source and checks](https://github.com/jayfeather9/spine-dynamic-graph/blob/c5fb7a7df41d1496f2aebede99595bea4a2d42b9/docs/implementation/residual_sparse_apply/README.md) |
| G+R HLS | `8a46817c102a411d70f43f05fa530e32be0806df` | [Prefetch/compact source map and build gates](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/8a46817c102a411d70f43f05fa530e32be0806df/docs/sharded_k4_prefetch_compact/README.md) |

The simulator pin precedes this documentation-only delivery. It is not changed
to a new numerical model by adding these documents. No old evidence manifest or
plugin was overwritten. External GraSU/ReGraph source identities are captured
in each generated packet's `manifest.env` and `inputs.tsv`; the ReGraph source
archive has no Git identity, so its recorded file hashes matter.

## Source Changes

### Spine

`SPINE_RESIDUAL_SPARSE_APPLY=1` selects a tile-local 65,536-bit touched-destination
bitmap. Accepted reductions mark destinations even when they cancel. Apply
visits marked destinations in ascending order and clears marks between tiles.
Nonzero redistributed dangling mass, including values below epsilon, forces a
dense Apply. FullPR remains dense. Default `0` preserves existing binaries.

The focused test compares all rank/residual words, frontier records, touched
counts, cancellation and repeated empty invocations against dense execution.
This is functional equivalence under the tested contract, not a measured FPGA
speedup. It does not implement the simulator's oracle-directed PR correction
replay as a new autonomous hardware correction engine.

### G+R

`--adapter-policy prefetch-compact` is a separate, default-off `sharded-k4`
profile. It ports the frozen `prefetch_gather_reuse` input/Gather path:

- Two 1024-row directory tiles; independent even/odd PMA burst readers with
  explicit parent and line-reservation limits, without removing dummy slots.
- Stable source-order join and lane compaction, eight edges per packet,
  bounded publication queues, and no mixed 4096-source windows.
- Independent source-window preload and TLAST termination; local destination
  IDs are not shifted a second time.
- Reusable Gather with first-use reset, forwarding, publication and clearing.
- SSSP/CC old-state Apply with explicit reads and a separate write port.
  Per-burst completion tokens protect the host's aliased read/write allocation.

Host opt-in `--prefetch-compact` selects the corresponding buffer padding,
reset policy and Apply ABI. Old five adapter pointer positions are retained,
but the 512-bit burst interface is not a drop-in replacement for old XOs.
Compile/link defaults and legacy commands remain unchanged.

## What Passed

| Gate | Evidence |
| --- | --- |
| Adapter | 132 cases per format, three formats: 396 checks |
| Adapter plus framed ReGraph | Six hand-fed and six connected-adapter invocations per SSSP/CC/PR policy: 36 checks |
| Integer Apply | Three partitions, separate and aliased buffers, SSSP/CC: 12 checks |
| Native hosts | Four algorithms compile; six-partition prepare-only/CPU-oracle checks pass for candidate and legacy profiles |
| Build generators | Four algorithms and both hardware targets, old command equivalence, source hashes and interface budget refusal |
| Spine sparse Apply | Prior 18-executable host suite passed; focused macro-enabled test rebuilt and rerun for this handoff |

The counts are not independent large-graph convergence experiments. In
particular, native host checks do not run the device. See [validation limits](VALIDATION.md).

## What Still Blocks Full Alignment

| Gate | Current finding | Required next evidence |
| --- | --- | --- |
| Physical master budget | Estimated complete G+R needs 34 masters for SSSP/CC, 39 for FullPR, 40 for ResPR; current admission budget is 32 | Explicit shared-port/integration topology, matching simulator arbitration, actual XO audit |
| Finite RTL behavior | C++ tests pass, but their streams are not bounded RTL queues | RTL co-simulation of empty/long/backpressured/repeated invocations and aliased Apply |
| Requested HLS schedules | Burst, forwarding, latency and compaction owners are present in source; achieved II/latency are not measured | Synthesis reports and interface inspection, followed by routing |
| PR-specific G+R stages | PR Gather is tested; PR Apply/source-prepare have not been newly ported to explicit-burst timing owners | Review and align those paths, not just the common input frontend |
| Spine PR correction | Oracle-directed simulator replay remains a model-to-implementation gap | Implement or explicitly constrain that evidence boundary |
| Hardware and model validation | No candidate XO, xclbin, hardware timing or stage calibration was produced | Common resident old-state/batch/convergence board checks after build admission |

These are remaining engineering tasks, not permission to change a model's
cycles by a constant factor. A four-frontend R path also does not automatically
match A4's resources: integer R here has 16 master instances and three full-state
copies; original A4 has 13 and four. The complete G update contributes another
18 master instances. The generated link gate must remain enabled.

## Safe Next Actions

Functional checks and generation commands are in [VALIDATION.md](VALIDATION.md).
Archived packets under `evidence/build_packets/` are inspection snapshots with
machine-local paths, not portable executable releases. Regenerate at the pinned
HLS commit with the correct dependency/tool roots before compiling.

Do not invoke `run_build.sh` expecting a complete admitted bitstream. The next
step is to resolve and model the physical sharing decision, or explicitly limit
an investigation to standalone component XOs. Full-system construction needs a
fresh aggregate memory admission, enforceable containment and a live reserve;
neither the small-test `prlimit` nor Spine's start-time memory check replaces
that policy. No FPGA job is left running by this delivery.
