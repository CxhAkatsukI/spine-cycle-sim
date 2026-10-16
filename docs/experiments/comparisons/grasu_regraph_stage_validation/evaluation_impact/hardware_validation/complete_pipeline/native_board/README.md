# Native Five-Shard G Host And Board Check

## Decision

The XRT-host preflight `g-native-board-host-v1` passes compilation, all eighteen
deterministic old host-model rows and three native host-model rows:
`NATIVE_G_HOST_MODEL_PASS_NOT_BOARD`. The separate `g-native-geometry-v4`
source regression passes all six paired-arm rows, exactly matching v1's setup
and numerical outputs after the shared-layout extraction. **Neither run
invokes an FPGA API or establishes native board correctness/timing.** There
is no original-G performance claim. The existing six-row
[native source capsule](../native_geometry/README.md) remains unchanged.

Portable deliverables retain frozen sources/runners, raw outputs and resource
records: [host preflight](host_evidence/index.json) and
[fresh source regression, including the failed v3](source_regression_evidence/index.json).
Their verifiers replay the archived numerical results without live source
or toolchain paths. This is evidence replay, not another hardware execution.

Eighteen focused Python tests pass. They check protocol/geometry rejection,
event conservation, prior raw-result replay, claim boundaries, device identity
guards, a memory-deadline failure that launches no child, and portable package
replay after the original source paths have been removed. Missing archived
source or runner identities are rejected. Synthetic event transcripts in
those tests are not FPGA measurements.

The broader 114-test gate also passes: native source checks, existing
continuous-board execution/handoff/delivery/supervisor tests, and repository
organization checks. It ran concurrently with R and A4 routing under a 1-GiB
hard limit, zero swap, CPUs 122--123 and an atomic 105-GiB admission budget
(1 GiB for the test, two 40-GiB compiler reservations and 24 GiB reserve).
The sampled child peak RSS was 39,516 KiB; the service peak was 44.1 MiB;
all cgroup OOM counters remained zero. Raw test output and resource records:
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/verification-native-board-v2`.
These tests do not replace fresh C++ execution or FPGA measurements.

## Declared Checks

The new C++ control shares production buffer binding, four search CUs,
dispatch, two full-cache halves, both cold-DDR CUs and the publication barrier
with the existing [single-shard host](../continuous_board/README.md). It does
not introduce a second XRT implementation or change the routed kernels.

| Scope | Required check |
| --- | --- |
| Geometry | 262,148 vertices; five 65,536-vertex destination shards; full 131,072-segment cache per half |
| Layout | Production builder, reservation, mapping, runtime plan and packing; shards 0/4 populated and 1/2/3 empty |
| Updates | Resident empty batch, 20 deletions, 20 reinsertion operations at a lower weight |
| Oracle | All 29,360,352 PMA words, including padding, plus independent external-ID weighted edge sets |
| Logical edges | 524,296; 524,276; 524,296 after the three batches |
| Coverage | CPU packing check requires hot-even/cold-even/hot-odd/cold-odd counts 6/4/6/4 in each nonempty batch; this is not a hardware counter |
| Old-state regression | Compile the shared old control and compare all eighteen deterministic old rows with frozen `g-continuous-host-v3` results |
| Native host preflight | Compile the new control against XRT and execute its three CPU-model rows without invoking any FPGA API |
| Event validation on board | Ten kernel/barrier events per shard per batch, including empty shards; eight update DMA events per nonempty batch |
| Metadata reuse on board | Prior shard completes before next shard is queued; metadata contents are read back and compared after every batch |

The production-plan allocation is 140,673,024 bytes. The 1,048,592-operation
reservation fixes capacity and mapping; only forty physical operations are
executed. Metadata contents do not change between these batches. Reusing CUs
across five different metadata buffers tests shard switching, **not changing
metadata generations at the same device addresses**. That separate hardware
lifecycle test remains open.

Old-output equivalence excludes only host wall-clock fields, which cannot
be bit-identical on a new execution. Geometry, batch counts, edge counts,
checked words, correctness flags and output order must match. The source
fixture extraction also has a separate fresh six-row C-simulation regression.
Attempt `g-native-geometry-v2` exhausted its 1,800-second memory-admission
deadline without launching a compiler or numerical child. It remains
`FAILED_RETAINED`, not a numerical mismatch or an OOM. Attempt v3 compiled,
then failed with `Resource temporarily unavailable` while creating the
source fixture's threads under `TasksMax=256`. Its raw failure is retained.
Fresh v4 raises only that service task limit to 1,024; the 4-GiB hard/3-GiB
high/zero-swap memory limits, 32-GiB reserve, frozen numerical sources and
assertions are unchanged. It compiles in 8.51 seconds and executes the full
six-row matrix in 42.40 seconds, with all cgroup OOM counters zero. Invocation:
`d809038bb3564147addbfb2a84d09f95`.

## Timing And Claims

The board control measures per-batch lowering/packing, update DMA and
kernel launch/wait through G completion. One-time graph reservation, device
programming and initial upload are separate. Independent oracle work, full
verification readback and report formatting are diagnostic costs, excluded
from G-ready latency. Device busy time is an interval union from raw events,
not a sum of overlapping CU times. Span and host-inclusive latency are
reported separately.

Even a passing native board check establishes only this synthetic G state and
binding scope. It is not algorithm convergence, complete G+R performance,
original-G publication reproduction or a real-trace speedup. Do not use CPU
preflight wall times as accelerator measurements.

## Code Map

| Owner | Responsibility |
| --- | --- |
| `cpp/tests/evaluation_impact/common_g/complete_pipeline/native_geometry/layout.hpp` | Shared pure host layout; no vendor HLS types |
| `cpp/tests/evaluation_impact/common_g/continuous_board/resident_state.hpp` | Shared physical packing, complete-state oracle and padding checks |
| `cpp/tests/evaluation_impact/common_g/continuous_board/device.hpp` | Existing XRT binding and sequential shard completion |
| `cpp/tests/evaluation_impact/common_g/continuous_board/execution.hpp` | Shared three-batch timing, verification and transcript emission |
| `cpp/tests/evaluation_impact/common_g/native_board/` | Native model and thin model/board CLI |
| `spine_cycle_sim/experiments/evaluation_impact/common_g/native_board/` | Separate preparation, bounded preflight, analysis, portable delivery and board launch |

## Reproduce And Monitor

From the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_g_native_board*.py'
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.native_board.study --help
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.native_board.execution --help
```

The preflight needs a fresh `--output`, pristine GraSU `--upstream`, production
`--integration`, installed `--xrt` and passing frozen `--reference`. Its own
cgroup is exactly 4 GiB hard, at most 3 GiB high, zero swap and group OOM kill.
It reserves all live bounded compiler budgets plus 32 GiB headroom, not just
current RSS. Unknown/unbounded compiler peers prevent admission. Each compile
or model execution has a 300-second deadline. The running supervisor has a
90,000-second lifetime and an 86,400-second finite memory wait; CPUs 124--125.
Memory admission does not require unrelated FPGA tools to exit.

```bash
systemctl --user status spine-g-native-board-host-20261016-v1.service
journalctl --user -u spine-g-native-board-host-20261016-v1.service --no-pager
```

Raw attempt:
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-native-board-host-v1`.
Invocation: `914efdd070f04912b93d6fd935db4b67`.

The delivered `native_board.delivery` capsule contains frozen sources, runner
snapshots, raw outputs, resource records and prior reference rows. Its verifier
independently replays the native matrix and old-state equivalence without live
toolchain paths. The [source-regression capsule](source_regression_evidence/index.json)
also retains v3's thread failure alongside v4's exact six-row pass.

```bash
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.native_board.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/native_board/host_evidence"))'
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.native_geometry.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/native_board/source_regression_evidence"))'
```

Actual board execution additionally requires a completed, timing-admitted
matching route, the original bitstream identity for comparison, 8-GiB hard/
7-GiB high containment and an exclusive board lease. The existing G/G+R queue
has priority; do not launch this additional control concurrently on its board
or treat lease rejection as permission to reset it.
