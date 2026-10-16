# Guarded Original-R Board Matrix

This package waits for one exact source-build service invocation, independently
rechecks its terminal artifact, then runs the offline-validated Release host on
one exclusively leased U55C. Waiting does not reserve a board. A failed,
restarted, changed or timed-out source build cannot launch the host.
The queue's `Requisite` dependency keeps the completed source unit inspectable
without restarting it; an unreferenced successful transient unit can disappear
before the next poll. The source invocation ID is still checked independently.

| Module | Responsibility |
| --- | --- |
| `preparation.py` | Freeze the independent audit, Release host, input/output oracle and live build manifest; declare the complete matrix |
| `admission.py` | Recheck all six XO/HLS identities and freshly extracted routed topology, clock and strict timing |
| `worker.py` | Hold one nonblocking board lease, forward its FD and exact BDF to bounded host children, record every attempt |
| `analysis.py` | Verify all fourteen replicas, padding/guards, independent oracle, kernel event identities and overlap-aware timing |
| `supervisor.py` | Wait for the exact service invocation, atomically admit memory, contain execution and recheck every raw result |
| `__main__.py` | Thin CLI requiring explicit `--execute` |

## Fixed Scope

The matrix is three graphs (`boundary_ring`, `skewed_sources`, `amazon`) x two
explicit divisor bindings (`author_initial`, `csr_degree`) x three repetitions
= eighteen board runs. It uses only the reviewed 11-Little/3-Big ABI. Offline
A4 checks do not authorize a different board ABI. Each graph retains its
audited original vertex IDs and complete input identity.

Each run performs **one static signed fixed-point PR superstep, `arg=0`**.
The resident wall window starts before argument binding/first enqueue and ends
after all kernel queues finish. Programming, preparation, DMA and readback are
outside that window. Event timestamps provide the union of busy intervals and
their complete span; overlapping kernels are never simply added. Free-running
mergers are not separately enqueued. Device cycles use the independently
admitted implemented 150-MHz clock.

This is a U55C same-platform control, not convergence, residual PR, host-inclusive
latency, publication-speed reproduction or a Spine speedup. Success is explicitly
`ORIGINAL_R_11L3B_GUARDED_BOARD_MATRIX_PASS_NOT_PUBLICATION_MATCH`.

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

Do not edit hash-pinned runner files after starting either queue. Source build,
board matrix, matched A4, actual adapter/K4 and publication comparison remain
separate acceptance gates. See the [campaign guide](../../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/original_regraph/README.md)
for actual run status and retained failures.
