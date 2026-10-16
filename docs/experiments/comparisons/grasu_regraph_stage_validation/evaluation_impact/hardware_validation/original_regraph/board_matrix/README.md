# Original-R Measured Board Control

## Decision

`original-r-board-supervisor-v4` passes all **eighteen actual U55C runs**:
three declared graphs x two explicit apply-divisor bindings x three repeats.
Every logical output, all fourteen output replicas, publication padding and
tail guards pass independent checks. Freshly extracted topology, 150-MHz DATA
clock and final setup/hold/pulse timing pass before board programming.

This closes the **same-platform original 11-Little/3-Big one-superstep board
control only**. It does not establish original-paper speed reproduction,
convergence, residual PR, host-inclusive latency, adapter overhead or Spine
speedup. A4 and the actual adapter/K4 path require their separate matrices.

The [portable capsule](evidence/index.json) includes 118 compact raw records,
the complete matrix, runtime/resource observations and two retained failed
startup attempts. Binary output replicas were rechecked before packaging;
large input/output binaries, hosts, XOs, xclbin and vendor tools are externally
hash-indexed rather than redistributed. Portable verification checks archive
integrity and all compact matrix records, not a new FPGA execution.

## Measured Window And Results

Each row executes one **static signed fixed-point PR superstep, `arg=0`**.
`author_initial` preserves the reviewed author's initial-property divisor;
`csr_degree` explicitly substitutes CSR outdegree. They are separate semantic
controls, not interchangeable repetitions. Inputs retain original vertex IDs.

The resident wall window begins before argument binding/first enqueue and
ends when all queues finish. Preparation, programming, DMA and readback are
excluded. Device event span/union uses the overlap-aware kernel timestamps;
overlapping kernels are not added together. Both windows are reported below.

| Graph | Divisor binding | Median resident wall, ms | Median event span/union, ms |
| --- | --- | ---: | ---: |
| boundary_ring | author_initial | 8.171378 | 1.231156 |
| boundary_ring | csr_degree | 8.062894 | 1.188865 |
| skewed_sources | author_initial | 2.297357 | 0.674320 |
| skewed_sources | csr_degree | 2.206814 | 0.524605 |
| amazon | author_initial | 22.816932 | 9.563118 |
| amazon | csr_degree | 21.814873 | 9.228968 |

Each entry summarizes three declared repetitions; the index retains their
minimum/median/maximum. Event span and union coincide for these runs. Do not
compare the resident wall time with another implementation's device-only
time or with the author's timer that starts after enqueueing.

## Artifact And Retained Attempts

The clean author revision is `365456826cef495285383d939907f847e05ad74b`.
The frozen validated runner is simulator commit `3ed4311`, with explicit
Xilinx OpenCL linkage and `XILINX_XRT=/opt/xilinx/xrt`. Offline Release/UBSan
validation passes all 48 rows before the board matrix. Device 1 is exclusively
leased and checked against BDF `0000:c1:00.1`; no automatic reset is used.

The fresh source-built xclbin SHA-256 is
`3e670e27d0ca04fc2b007c6f055c3c6149e6859f0701947a8d48cab245e39409`.
The implemented timing summary reports WNS +0.002 ns, WHS +0.009 ns and no
setup/hold/pulse failures at the admitted clock. It is not the author's older
automatically reduced-clock prebuilt.

| Retained attempt | Outcome and treatment |
| --- | --- |
| `original-r-source-route-v6` | Compiler/link completed, but old analyzer confused AXIS connections with HBM bindings; original `FAILED_RETAINED` report remains unchanged. Fresh independent ABI/HBM/AXIS/clock/strict-timing review admits this exact artifact, not a new implementation. |
| `original-r-board-supervisor-v2` | Generic OpenCL linkage resolved to the CUDA ICD; gate rejected before child launch/programming. No performance row. |
| `original-r-board-supervisor-v3` | Exact Xilinx-linked host launched but lacked `XILINX_XRT`, so platform enumeration failed. Zero admitted rows; programming status remains conservatively unknown in the raw report. |
| `original-r-board-supervisor-v4` | Explicit service environment; all eighteen guarded board rows pass. |

Raw evidence root:
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.
The capsule preserves the two failed board attempts and the independent
review's original source-route result identity. No failed result is rewritten.
The first packaging recheck rejected tuple/list representation differences;
the retry normalizes JSON serialization only, with changed-clock and corrupted
replica regression tests. Frozen numerical results and timing gates did not change.

The full original-R Python regression passes 233 tests; repository organization
passes fifteen tests, document-layout/catalog checks and `git diff --check`.
These unit tests include mocked FPGA transcripts, not additional board runs.
Bounded test service invocations are `43677a1876424907aa041f650a68fca5` and
`7e85bc724ca04d81835d7def7fa75ba0`; their user journal retains the raw logs.
No simulator, SST or full-repository numerical regression is claimed here:
this change adds evidence packaging and does not change numerical execution.

## Memory Safety

The complete matrix took 76.720 s wall time. Sampled simultaneous process-tree
peak RSS was 449896 KiB, with minimum system available memory approximately
129 GiB and zero cgroup memory/OOM events. The enclosing service enforced
8-GiB hard / 7-GiB high / zero-swap limits, group OOM handling and CPUs 124--125.
Admission budgeted both active compiler limits plus the declared system reserve.
Other FPGA tools did not need to exit. These CPU/memory observations are not
accelerator timing measurements.

## Verify And Reproduce

From the simulator worktree root:

```bash
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/original_regraph/board_matrix/evidence"))'
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution --help
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution.delivery --help
```

The [execution owner](../../../../../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/board_execution/README.md)
defines exact invocation pins, exclusive lease, XRT environment and bounded
launch policy. Use new unit/output names and a separately admitted exact
artifact; do not reprogram the board merely to verify the portable capsule.
The code supports sealing A4 under its distinct status, but this capsule
contains **only 11+3 measurements**. See the [parent guide](../README.md) for
the offline input findings and original-paper limitations.
