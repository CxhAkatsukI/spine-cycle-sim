# Continuous G Host Preflight

## Decision

`g-continuous-host-v1` passes XRT host compilation and all eighteen **host-model**
rows: `CONTINUOUS_G_HOST_MODEL_PASS_NOT_BOARD`. Six AU/SU/WK cases each apply an
empty batch and two consecutive half-batches without restoring PMA state.
The execution used `--model-check`; it did not enumerate, program or run an
FPGA. No board latency, original-G match or complete G+R admission is claimed.

The [portable evidence index](evidence/index.json) contains the frozen host,
inputs/contracts, compiler/header identities, raw logs, analysis and resource
records. The XRT-linked binary SHA-256 is
`ef8a5b484e3729d136e3354d409b3510166c66cddb82ce817f99ae438f4f9694`;
348 compiler dependencies are pinned. These identify compilation, not the
runtime XRT libraries/driver or a programmed bitstream.
The frozen v1 analyzer is retained unchanged. The delivery review and tests
reanalyze its raw output with the stricter current analyzer, including finite
nonnegative times, exact word counts and host/device claim separation; this
is an analysis review, not a second execution or changed FPGA source.

## Inputs And State

The unchanged production builder, lane-aware 23-channel runtime plan and
packing are reused from the [real-input source check](../host_prepared/README.md).
The inherited `contract.json` remains unchanged; `continuous_contract.json`
selects its six native 65,536-vertex-partition cases, excluding the separate
1,024-vertex functional smoke. These compact AU/SU/WK slices start with 8,192
edges and use mixed-512 or weight-change-4096 inputs. Weight changes lower to
delete/insert pairs, so the latter has 8,192 physical updates.

Each hot-cache half retains all 131,072 segments. PMA and metadata BOs are
allocated/uploaded once; only batch updates are subsequently transferred.
The expected physical state is advanced by an independent linear-segment
mutation oracle and checked against the external-ID weighted edge set.
Every batch checks all PMA words, including padding. The model smoke also
injects restoration of the initial PMA after each nonempty batch and requires
the state check to reject it. Board mode additionally reads and checks resident
metadata at the same addresses.

This differs from the historical native host's `GRASU_UPDATE_REPEATS` loop,
which restores initial PMA on each repeat. That host and its old results are
unchanged. The new host's continuous-state path is not yet a board-verified
replacement. These real cases contain hot updates only; cold updates,
metadata refresh and native multi-shard operation require separate hardware
checks before admitting the full baseline.

## Code Owners

Paths below are relative to the repository root.

| Owner | Responsibility |
| --- | --- |
| `cpp/tests/evaluation_impact/common_g/continuous_board/model.hpp` | Unchanged production preparation, physical batch packing and independent full-state oracle |
| `cpp/tests/evaluation_impact/common_g/continuous_board/xrt.hpp` | Checked XRT/OpenCL setup, HBM buffers and monotonic event profiling |
| `cpp/tests/evaluation_impact/common_g/continuous_board/device.hpp` | Four search CUs, dispatch, both caches, both DDR paths, completion barrier and persistent BO bindings |
| `cpp/tests/evaluation_impact/common_g/continuous_board/control.cpp` | Thin model/board modes and explicit timing/output boundaries |
| `spine_cycle_sim/experiments/evaluation_impact/common_g/continuous_board/` | Separate preparation, bounded host-only execution, analysis and evidence packaging |

The pure preparation header no longer imports vendor simulation types.
Its fresh [42-row regression](../host_prepared/native_input_regression/equivalence.json)
matches the previous source execution byte-for-byte, including parsed
counters and classified diagnostic counts. This refactor does not change
production HLS, simulator numerical components or an SST build list.

## Timing Boundary

These fields are implemented for future board measurements. The preflight's
host wall times are **not FPGA performance results**; its kernel fields are zero.

| Field | Window |
| --- | --- |
| `one_time_setup_ms` | Input parsing/builder/reservation, XRT program/buffer setup and initial uploads; outside the resident batch window |
| `host_preparation_ms` | Per-batch physical lowering and four-lane packing |
| `transfer_wall_ms` | Batch-update DMA enqueue through DMA completion |
| `launch_wait_ms` | Kernel argument setup, G launch/wait and publication barrier |
| `g_ready_wall_ms` | Wall time from batch preparation through G/barrier completion |
| `kernel_busy_ms` / `kernel_span_ms` | Union of overlapping G/barrier event intervals / first-start to last-end; not a sum of concurrent CU times |
| `oracle_ms` / `verification_readback_ms` | Independent oracle and diagnostic full-state readback, recorded separately |

`g_ready_wall_ms` is isolated-G ready-to-handoff timing, not algorithm
update-to-convergence or complete host-inclusive G+R timing. It excludes
adapter/ReGraph, algorithm result publication, the diagnostic readback/oracle
and event/report formatting. A complete-system comparison must measure its
own end boundary rather than relabel this field.

## Reproduce And Verify

From the repository root:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.study --help
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.delivery --help
python3 -m unittest tests.test_grasu_continuous_board tests.test_grasu_host_prepared -v
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/continuous_board/evidence"))'
```

Use a fresh output directory, pristine `GraSU_kernels/src` as `--upstream`,
the production G+R checkout as `--integration` and `/opt/xilinx/xrt` as `--xrt`.
The runner uses C++20/O2, warnings as errors, assertions and `-MD` including
system/vendor headers. Every compiler/model process is limited to 4 GiB hard,
3 GiB high, no swap, CPUs 124--125, 104 GiB available-memory reserve and
900 seconds. Bound the supervisor separately. The reserve accommodates two
40-GiB FPGA tool budgets plus 24 GiB for system/background work; those tools
need not exit when the bounded budgets fit.

Compilation took 5.41 s and about 360 MiB peak process RSS. Each case took
0.15--0.21 s with less than 74 MiB peak process RSS. Raw evidence is at
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-continuous-host-v1/`,
systemd invocation `b804313a60f04011bedcceba4fbbbd7b`. Host checks do not execute
the production search/cache logic; the independent source matrix covers that
separate functional requirement.

The focused suite passes all 223 tests, including raw-output reanalysis,
claim-promotion/corruption rejection, both committed capsule checks and the
42-row input-refactor equivalence check. It ran with a 2-GiB physical memory
bound and about 92 MiB sampled peak process-tree RSS. Raw verification logs
are retained at `verification-continuous-host-v3/` under the campaign root;
the earlier v1/v2 test runs are retained as well.

## Remaining Board Gates

The C++ `--board` path is compiled but unexecuted. Before using it, require a
timing-accepted, identity-pinned **complete new-G** bitstream, not the separate
adapter-only build or an older search/cache bitstream. Pin the XRT runtime
libraries/driver and device identity, hold an exclusive board lease, and run
under bounded memory/time supervision with raw event and failure retention.
No automatic board launcher/admission is delivered in this checkpoint.

Board checks must validate raw profiling intervals, full state, continuous
batches, cold updates, metadata lifecycle and multi-shard bindings. Integrated
RTL/backpressure remains a separate open gate. Only then compare isolated G
against original G under matched inputs/boundaries, followed by the independent
R controls, physical G+R handoff and Spine convergence matrix. The
[campaign guide](../../README.md) owns these broader acceptance decisions.
