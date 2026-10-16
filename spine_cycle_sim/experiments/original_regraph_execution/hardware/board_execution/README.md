# Guarded Original-R Board Matrix

This package waits for one exact source-build service invocation, independently
rechecks its terminal artifact, then runs the offline-validated Release host on
one exclusively leased U55C. Waiting does not reserve a board. By default a
failed, restarted, changed or timed-out source build cannot launch the host.
The queue's `Requisite` dependency keeps the completed source unit inspectable
without restarting it; an unreferenced successful transient unit can disappear
before the next poll. The source invocation ID is still checked independently.

| Module | Responsibility |
| --- | --- |
| `preparation.py` | Freeze the independent audit, Release host, input/output oracle and live build manifest; declare the complete matrix |
| `admission.py` | Recheck all selected XO/HLS identities and freshly extracted routed topology, clock and strict timing |
| `worker.py` | Hold one nonblocking board lease, forward its FD and exact BDF to bounded host children, record every attempt |
| `analysis.py` | Verify all selected replicas, padding/guards, independent oracle, kernel event identities and overlap-aware timing |
| `supervisor.py` | Wait for the exact service invocation, atomically admit memory, contain execution and recheck every raw result |
| `delivery.py` | Independently replay raw output/route checks, retain failed attempts, seal and verify a portable measured-control capsule |
| `__main__.py` | Thin CLI requiring explicit `--execute` |

## Fixed Scope

The matrix is three graphs (`boundary_ring`, `skewed_sources`, `amazon`) x two
explicit divisor bindings (`author_initial`, `csr_degree`) x three repetitions
= eighteen board runs **per topology**. The default `original_example` uses
11 Little + 3 Big, six unique XOs and fourteen output replicas. Explicit
`--topology a4` selects the author's generated four-Little/zero-Big path,
four unique XOs and four output replicas. These are separate matrices, not
interchangeable binaries. Each graph retains its audited original vertex IDs
and complete input identity.

A4 requires an independently recompiled/offline-validated host whose report
explicitly admits `board_abis = ["original_example", "a4"]`. Historical hosts
that rejected A4 remain valid only for the original topology. The input
descriptor, source-route manifest, terminal route status, compiled ABI, freshly
extracted artifact topology and child result must all agree with the selected
configuration. A4 still uses the author's nine HBM banks, not our K4/23-channel
layout; four lanes alone do not establish equal resources.

Each run performs **one static signed fixed-point PR superstep, `arg=0`**.
The resident wall window starts before argument binding/first enqueue and ends
after all kernel queues finish. Programming, preparation, DMA and readback are
outside that window. Event timestamps provide the union of busy intervals and
their complete span; overlapping kernels are never simply added. Free-running
mergers are not separately enqueued. Device cycles use the independently
admitted implemented 150-MHz clock.

This is a U55C same-platform control, not convergence, residual PR, host-inclusive
latency, publication-speed reproduction or a Spine speedup. Success is explicitly
`ORIGINAL_R_11L3B_GUARDED_BOARD_MATRIX_PASS_NOT_PUBLICATION_MATCH` or
`A4_R_GUARDED_BOARD_MATRIX_PASS_NOT_PUBLICATION_MATCH`, respectively.

## Bounded Execution

The supervisor and worker share an 8-GiB hard / at-most-7-GiB high / zero-swap
cgroup, group OOM handling and a bounded service lifetime. Before board work,
atomic admission includes every peer's full finite budget, a 24-GiB reserve and
an 8-GiB background allowance. The process-tree watchdog keeps 32 GiB available
and imposes an 11,200-second worker timeout; each host run has 600 seconds.
Neither the queue nor the worker resets or retries a board automatically.

The existing shared board-lock namespace prevents collision with the G queue.
The lock must be a regular nonsymlink file; its FD is forwarded explicitly to
the guarded C++ child, which also checks the exact expected BDF before programming.
Runtime libraries, driver/device identity, sources, inputs and outputs remain
hash-pinned. Failure after a launch may leave programming status unknown; that
uncertainty is retained, not reported as "no board programmed."

Run from the worktree root with fresh unit/output names and the exact successful
or still-live source service invocation ID:

```bash
systemd-run --user --unit=original-r-board-fresh \
  -p Requisite=exact-source-build.service \
  -p MemoryMax=8G -p MemoryHigh=7G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p CPUQuota=200% -p RuntimeMaxSec=111600 -p TasksMax=256 \
  -p TimeoutStopSec=30 -p KillMode=control-group \
  --setenv=XILINX_XRT=/opt/xilinx/xrt \
  --working-directory="$PWD" \
  /usr/bin/taskset -c 124,125 /usr/bin/python3 -m \
  spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution \
  --audit /path/to/passing/input-audit \
  --control /path/to/passing/offline-control \
  --route /path/to/frozen/source-build \
  --route-unit exact-source-build.service \
  --route-invocation 0123456789abcdef0123456789abcdef \
  --device 1 --output /path/to/fresh/board-queue --execute
```

For A4 add `--topology a4` and supply the distinct generated-A4 source build
and the new A4-capable validated host. Adding the flag cannot authorize the
11+3 prebuilt or bypass route/clock/timing admission.

Use the exact Xilinx OpenCL library admitted by `control_build.py` and set
`XILINX_XRT` explicitly in the service. Generic `-lOpenCL` may resolve to an
unrelated CUDA ICD; a correctly linked host can also fail to enumerate the
Xilinx platform if the service lacks this environment variable. Neither
startup failure is a performance measurement.

## Retained Analysis Failure Review

The old source-route analyzer treated AXIS entries in `CONNECTIVITY` as HBM
bindings. A compiler-successful build can therefore retain the single error
`ValueError('implemented HBM bank/argument bindings differ from author topology')`
despite producing an inspectable artifact. The optional
`--review-retained-analysis-failure` is a **read-only independent review**, not
a way to mark that old run successful or accept failed physical timing.

Only the exact source invocation's terminal exit code 1 is eligible. Its raw
report must have that one error, successful metadata extraction, no admitted
analysis, and no hardware/publication claims. Complete successful compile/link
steps, every XO and HLS report, source/binary/utility hashes, freshly extracted
HBM **and** AXIS topology, implemented clock, and global setup/hold/pulse timing
are still independently checked. Additional errors, timeout/OOM, changed source,
ABI mismatch or negative slack prevent a board launch. In particular the old
A4 route with global HBM WNS -0.098 ns remains rejected.

Use a fresh supervisor worktree/output after the old default queue has stopped.
Add the flag to the command above, keeping the original source invocation ID.
For an already failed source unit, omit `Requisite` rather than restarting the
compiler. Never add a dependency that restarts it. The fresh report preserves
the original result hash and error under `routed_admission.retained_analysis_failure`;
the original `FAILED_RETAINED` report is never rewritten. Passing this review
only admits the artifact to the same complete eighteen-run guarded matrix.

Do not edit hash-pinned runner files after starting either queue. Source build,
board matrix, matched A4, actual adapter/K4 and publication comparison remain
separate acceptance gates. See the [campaign guide](../../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/original_regraph/README.md)
for actual run status and retained failures.

After a terminal pass, `python3 -m
spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution.delivery
--help` describes sealing a fresh capsule. Packaging rechecks all binary
replicas and the exact routed evidence before archiving compact JSON/text
records. Large graphs, binary outputs and vendor artifacts stay externally
hash-indexed; portable verification does not claim to rerun those outputs.
