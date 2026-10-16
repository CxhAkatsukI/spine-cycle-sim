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
| `supervisor.py` | Wait for one pinned route invocation, require routed admission, then run isolated G and resident G-to-SSSP matrices sequentially |

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

## Conditional Board Queue

The conditional supervisor waits only for the **required new-G bitstream**,
not for unrelated FPGA tools to exit. It freezes both guarded host reports,
binaries, sources/dependencies, route inputs, reference bitstream and imported
runner owners. The route's systemd invocation must remain unchanged; an active
service with `Result=success` is still running, not admitted. Route failure,
queue timeout, source changes or timing rejection stop before board execution.

Once strict routed admission passes, the existing bounded execution engine
runs all six G inputs three times, followed by all nine resident G-to-SSSP
inputs three times. These would produce 54 and 81 batch rows respectively,
not 135 rows already measured. The board lease, idle/health/BDF checks, raw
event validation, 600-second per-case watchdog and memory limits are unchanged.
A busy board or failed case stops the queue; there is no automatic reset,
retry, alternate-bitstream substitution or partial-matrix admission.

Inspect the explicit execution arguments with:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor --help
python3 -m unittest tests.test_grasu_continuous_supervisor -v
```

Supply `--g-preflight` for `g-continuous-host-v3`, `--gr-preflight` for
`gr-continuous-host-v4`, `--route`, `--original`, a fresh `--output`, and the
required `--route-unit` / `--route-invocation`. `--execute` is mandatory.
Use an enclosing 8-GiB hard/7-GiB high/no-swap/group-OOM user service with a
bounded lifetime. The default route wait is 24 hours; allow the additional
7.5-hour worst-case matrix budget in the service lifetime. No board lease is
held while waiting for routing. `results.json` retains route states, frozen
identities and child reports, including failures and actual `board_started`.

The 277-test focused suite passes, including twelve conditional-supervisor
tests. Raw logs and resource records are retained in
`verification-gr-board-supervisor-v1/`: 8.56 seconds, 104304 KiB sampled peak
process-tree RSS, 2-GiB hard bound, CPU 123 and 104-GiB reserve. These tests
mock board execution; they are not FPGA correctness or performance results.

The original queue ran as `spine-g-gr-board-20261016-v1.service`, invocation
`932dc401fcfc4071a6ecfc6f2d854e81`, from commit `006eee0`. Its initial report
is `WAITING_FOR_REQUIRED_ROUTE`, with 711 frozen file identities and
`board_started: false`. It follows only
`spine-grasu-complete-route-20261016-v1.service`, invocation
`873fe3b111d3460b94457140f3df58be`. Raw status and eventual child matrices stay
under the campaign's `g-gr-board-supervisor-v1/` directory. The enclosing
service has 8-GiB hard/7-GiB high/no-swap/group-OOM limits and a 36-hour lifetime.
This launch record is not a guarantee that routing or either board matrix
will pass; inspect the current report rather than this initial checkpoint.

The v1 queue subsequently stopped with `FAILED_RETAINED` when the exact G
route hit its six-hour bitstream-generation deadline. `board_started` remains
false. The failed queue and route are retained; a new link attempt requires
a new board-queue directory, service and explicit invocation identity.

The v2 queue also stopped before programming: it pinned `manifest.json`
while the route was memory-queued, but the route legitimately appends its
environment-preflight identity after admission. Comparing all 710 queue pins
and both host reports confirmed that only that manifest changed, not the
kernel sources, host binaries, inputs or dependencies. The failed report
remains unchanged at `g-gr-board-supervisor-v2/`.

The fresh `spine-g-gr-board-20261016-v3.service`, invocation
`7fc3dc0aa67e4fa08981ebb73d65ed95`, starts after that append and pins the final
manifest. It follows only G route v2, invocation
`49a3071d4a9244ff8f83e3429295d2a1`, from the frozen `08f8842` runtime.
Its raw directory is `g-gr-board-supervisor-v3/`; status is
`WAITING_FOR_REQUIRED_ROUTE`, with `board_started: false`. The service has
8-GiB hard/7-GiB high/no-swap/group-OOM limits, a 48-hour lifetime and a
133,200-second route-wait bound. Future queues using this frozen supervisor
must start after the route has appended its preflight pin. This lifecycle
requirement does not permit ignoring any later manifest or source change.
