# Original ReGraph Hardware Preflight

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
2. Add a bounded fixed-BDF host with safe explicit publication allocation,
   both named divisor controls and complete output checks. Retain the
   original-host behavior as a separately labeled control.
3. Record the entire resident compute span and per-kernel events, not only
   the author's late wall timer or a sum of overlapping lanes. Measure host
   preparation separately, use declared repeats and retain every failure.
4. Only then compare original R, resource-disclosed A4 and actual adapter/K4;
   publication reproduction and Spine speedup remain later, separate gates.
