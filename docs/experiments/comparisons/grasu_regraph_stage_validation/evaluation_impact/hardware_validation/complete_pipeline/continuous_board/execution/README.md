# Bounded Continuous-G Board Execution

## Checkpoint

The launcher and analyzers are implemented; **the board matrix has not run**.
The complete-new-G route is still running. The fresh guarded host compiles and
passes eighteen host-model rows, not hardware measurements. The separate
adapter-only route cannot satisfy this launcher's new-G admission.

`g-board-unfinished-gate-v1` exercised the actual entry point with `--execute`
against that live route. It correctly stopped with `FAILED_RETAINED`,
`board_started: false` and no attempted FPGA calls. This is a successful
rejection check, not a failed hardware execution or a board correctness pass.
Its results are retained under
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.

The read-only `g-board-runtime-readonly-v1` check also passes on device
`0000:82:00.1`: the shared lease/occupancy check, twelve resolved runtime/tool
pins, driver identity, platform health and MIG calibration were inspected.
It did not program a bitstream, create an OpenCL kernel or measure G latency.
Its raw platform/loader output and identity remain in the same campaign root.

All 241 focused regressions pass, including both preflight capsules and
eighteen-row non-timing equivalence, route/lease guards, strict event analysis,
the 42-row source regression and existing process/memory-watchdog tests.
`verification-continuous-board-v3/` retains the complete command and raw logs;
the suite used a 2-GiB physical bound, no swap, CPU 123, a 104-GiB reserve,
8.35 seconds and about 91 MiB sampled peak process-tree RSS. Earlier checks
remain intact. Documentation-layout, catalog and diff-whitespace checks pass.

## Admission And Ownership

Code lives in
`spine_cycle_sim/experiments/evaluation_impact/common_g/continuous_board/execution/`.

| Module | Responsibility |
| --- | --- |
| `route.py` | Require a completed unchanged link, new search and full-cache XOs, the expected 22 CUs, matching 150-MHz topology/connectivity and final setup/hold/pulse timing |
| `runtime.py` | Resolve/pin actual ELF and dynamically loaded XRT-core libraries; record driver, PCIe BDF and healthy calibrated U55C platform under the lease |
| `events.py` | Recompute event unions/spans, reject missing/duplicate events, invalid intervals, inconsistent DMA/batch order, state or reported timing |
| `study.py` | Validate frozen host preflight; acquire shared board lease; execute all cases/repetitions with resource limits and failure retention |

The host rejects a BDF mismatch before constructing its OpenCL program. The
existing shared board lease and occupancy check are reused, not replaced by
a private lock. The runner rejects inherited XRT/emulation/loader overrides
and local `xrt.ini` files. Runtime and source identities are rechecked between
cases. It neither resets an occupied board nor retries a failed FPGA call.

## Matrix And Timing

The first matrix has six **single-shard, hot-only** native cases: AU/SU/WK
mixed-512 and weight-change-4096. Every case runs an empty batch and two
consecutive half-batches without restoring resident PMA. The default three
repetitions produce 54 checked batch rows, with full PMA/padding and metadata
readback after each batch. Repetitions start separate resident sessions;
one-time input/program/upload setup is reported outside the batch window.

Measured ready-to-handoff wall time includes physical update preparation,
DMA and G/barrier launch/wait. Raw four-timestamp events cover each of the
nine G kernels, publication barrier and nonempty update-DMA lanes. Overlapping
CU times are unioned, never summed. Diagnostic oracle/readback and event
reporting are separate. These windows are **not** adapter/ReGraph execution,
algorithm convergence or complete G+R timing.

Even a passing matrix sets only `board_correctness_measured: true`.
Integrated RTL, cold/multi-shard/metadata-lifecycle checks, timing-model
validation, original-G comparison, publication match and complete baseline
admission remain separate requirements.

## Reproduce

From the repository root, inspect the arguments first:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.study --help
```

Supply `--preflight` pointing to `g-continuous-host-v2`, `--route` to a completed
new-G route, `--original` to the old reference xclbin and `--output` to a fresh
directory. The default performs route admission only. Add `--execute`,
`--device 0` and `--repeats 3` to run the board matrix. Both modes reject unfinished
routes; neither silently substitutes an older bitstream.

Run execution under a user systemd service with `MemoryMax=8G`,
`MemoryHigh=7G`, `MemorySwapMax=0`, `OOMPolicy=kill` and a bounded supervisor
lifetime (for example `RuntimeMaxSec=14400`). The runner verifies cgroup-v2
containment, pins workers to CPUs 124--125, enforces 600 seconds per case and
an 8-GiB process-tree limit, and requires 104 GiB available-memory reserve.
The reserve accommodates two 40-GiB compiler budgets and 24 GiB system work.
Other FPGA tools need not exit if these full budgets fit. Insufficient memory
or an occupied board is retained as a rejection, never a passing measurement.

Results, raw stdout/stderr, event analysis, runtime identity and resource
records stay in the unique output directory. Do not promote a launcher test,
model result or running route into a hardware performance claim.
