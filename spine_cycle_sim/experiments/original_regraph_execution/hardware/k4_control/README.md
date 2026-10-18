# Matched Adapter/K4 Control

This owner prepares the actual production destination-sharded K4 input from
the **unchanged original A4 captures**. It is an offline semantic prerequisite,
not a cycle model, vendor simulation, FPGA execution, original-publication
reproduction, default-algorithm equivalence or performance result. No G kernel,
source preparation or convergence is included in this one-static-superstep
control. Four frontends with 23 graph channels are not equal resources to A4.

| Module | Responsibility |
| --- | --- |
| `inputs.py` | Exact passing original-R validation and independent arithmetic audit; unchanged captures, complete matrices and clean production revision |
| `analysis.py` | Independent CSR gather, duplicate eligibility, binary32 payload hashes, exact profile, permutation and all 24 predeclared rows |
| `build.py` | Explicit Release/UBSan flags and unmodified production-header include path; no XRT/vendor runtime |
| `board_build.py` | Explicit XRT-linked guarded host and pure-schedule builds; no bitstream admission |
| `board_analysis.py` | Independent complete prepared/raw-buffer checks, external projection, exact schedule, dependency and overlap-aware measured timing validation |
| `board_plan.py` | Recheck every prepared buffer and the complete source closure; freeze six cases, three repeats and explicit source-version limitations |
| `board_matrix.py` | Retain six unsupported rows and summarize all twelve independently checked FPGA runs without hiding missing/invalid times |
| `board_worker.py` | Exclusive leased board execution, fresh state each run, complete raw readbacks, log pins and no reset/retry after programming |
| `board_study.py` | Prepare-only admission plan or explicit execution after an exact successful FullPR return, strict route review and finite memory admission |
| `study.py` | Full-budget atomic admission, bounded offline or explicit board-host-preparation matrix, records, failure retention and unchanged closure |

The [C++ model contract](../../../../../cpp/tests/original_regraph/integrated/README.md)
describes the full graph/state buffers, guards, production placement and
numeric differences. Original A4 uses a truncated fixed-point payload;
K4 uses binary32. The two explicit divisor bindings, damping 108/128, zero
base/dangling share, numeric initial contributions, one FullPR step and
rank-zero initial state must stay fixed. Each is checked against its own
independent arithmetic oracle, not by declaring the fixed/float words equal.

## Matrix

Three graphs (`boundary_ring`, `skewed_sources`, `amazon`) x two divisor
bindings (`author_initial`, `csr_degree`) x two repetitions x Release/UBSan
= **24 predeclared rows**. Unsupported duplicate-edge graphs remain in that
matrix with their duplicate count and first repeated edge. They must reject
before output creation in both builds and both repetitions. They are not
successful controls, are not deduplicated, and cannot supply speedups.
Supported cases must match independently recomputed gather/payload hashes,
exact graph/task/PMA edges, full guarded allocation and bank accounting;
Release, UBSan and repetitions must agree. Failing compilation, unexpected
diagnostics, wrong rejection reason, changed pins or memory-limit events
retain a failed attempt rather than reducing the matrix.

`boundary_ring` is known to contain 64 duplicate CSR records, first repeated
edge `352 -> 43409`. The production PMA key is a single source/destination
edge, so that frozen multiedge input is unsupported. The bounded focused
model tests passed for `skewed_sources`; the retained complete study below
additionally admits Amazon. The complete study result, not just these tests,
determines the available comparison scope.

## Retained Offline Result

Campaign root: `/data/chuxiao/experiments/baseline_hardware_validation_20261015`.
The immutable `original-r-k4-runner-8dd43e1` snapshot ran all 24 declared rows
in `original-r-k4-offline-v2/results.json`. Its status is
`MATCHED_K4_A4_OFFLINE_MATRIX_COMPLETE_NOT_HARDWARE_OR_PERFORMANCE_MATCH`:
16 passing rows, eight unsupported duplicate-edge rows, no errors and no
memory-limit/OOM events. Amazon and `skewed_sources` each pass both bindings,
both builds and both repetitions. Amazon has zero duplicate records;
`boundary_ring` retains its 64 duplicates and never supplies a passing output.

Result SHA-256:
`cbf120edd62fa73d370ef8ad53e35ad40812900c1e3ef686332aa6ee1f8e5e9f`.
Snapshot archive SHA-256:
`dde1df4e405ddd0b04cc33a2370d2896db092edfe6f1383c4151e01c667cf730`.
The service `spine-original-r-k4-offline-20261018-v2.service` finished in
120.9 seconds with a 1.4-GiB peak under a 4-GiB hard limit, 3584-MiB high
limit, zero swap, group-OOM containment, 100% CPU and affinity 123.

`original-r-k4-offline-v1` remains a failed harness attempt: compilation
finished, but dependency provenance rejected GCC's noncanonical target.
The actual build command now uses `-MT probe`; no graph or numerical rule
changed. The corrected command and dependency closure are tested directly.
All 253 original-ReGraph focused tests subsequently passed in 23.9 seconds
under a separate 2-GiB zero-swap cgroup (401.9-MiB peak).

These are CPU semantic/preparation checks. They do not measure actual K4
latency, establish same-resource/publication equivalence, admit a bitstream
or produce a new Spine speedup. The actual adapter/K4 board path remains a
separate gate.

## Board-Host Checkpoint

The [C++ host guide](../../../../../cpp/tests/original_regraph/integrated/README.md#guarded-board-host-components)
defines the new `prepare`/`board` interface and small schedule/device/report
owners. The six focused board-host tests passed in Release and UBSan without
programming an FPGA: exact preparation arithmetic, complete scheduling with
idle/reused workers, event overlap/dependencies, XRT library closure, duplicate
rejection and missing-lease rejection before device context/programming.
Unit `spine-k4-board-host-tests-20261018-v1.service` took 20.1 seconds and
peaked at 513.4 MiB under a 2-GiB zero-swap cgroup, CPU quota 100%, affinity
123. The test outputs were temporary, not retained FPGA evidence.
The complete 259-test original-ReGraph regression then passed in 44.0 seconds
(526.7-MiB peak) in `spine-original-r-regression-20261018-v4.service`, using
the same containment and affinity with a 240-second timeout. Documentation
layout/catalog checks and all 15 repository-organization tests also passed.

The expanded nine-test host suite passes in
`spine-k4-board-host-tests-20261018-v3.service`: 21.6 seconds, 494.8-MiB
peak, same containment. It independently checks complete prepared target
files, rejects corrupted canaries/projections/metadata, and exercises the
readback/timing validator with explicitly fabricated test records. Those
records are not FPGA evidence. The preceding v2 test service failed because
the host `/tmp` filesystem was full; v3 sets `TMPDIR=/data/chuxiao/tmp`
without deleting others' files or changing the model.
The subsequent full original-ReGraph regression passed all 263 tests in
46.1 seconds, with a 507.4-MiB peak in
`spine-original-r-regression-20261018-v5.service` under the same containment.

The host preserves full raw readbacks and only promotes executed/unverified
to guarded-pass after exact buffer checks. Python independently compares
every raw buffer with the separately prepared pinned target, then rechecks
logical projection, event identities/dependencies and measured windows.
The board execution owner is implemented and tested with fabricated unit
fixtures; actual route/ABI qualification and repeated FPGA execution remain pending.
Do not invoke its `board` CLI on an unqualified xclbin. No actual K4 timing
or additional publication/default-profile equivalence is claimed.

## Run

Use a clean/frozen runner and a fresh output. The exact prior inputs are under
`original-r-control-validation-v4/inputs/a4` in the campaign below. A snapshot
without `.git` is identified by its complete file pins, not an invented Git
revision. All loaded runner modules, C++ files, production dependencies,
compiler, original audit closure, inputs, binaries and outputs are rehashed.

```bash
CAMPAIGN=/data/chuxiao/experiments/baseline_hardware_validation_20261015
systemd-run --user --wait --pipe --unit=original-r-k4-offline-fresh \
  -p MemoryMax=4G -p MemoryHigh=3584M -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p CPUQuota=100% -p CPUAffinity=123 -p RuntimeMaxSec=1800 \
  -p TimeoutStopSec=30 -p KillMode=control-group -p TasksMax=128 \
  --setenv=TMPDIR=/data/chuxiao/tmp \
  --working-directory="$PWD" \
  /usr/bin/python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.k4_control.study \
  --validation "$CAMPAIGN/original-r-control-validation-v4" \
  --arithmetic "$CAMPAIGN/original-r-k4-arithmetic-v1" \
  --original /absolute/clean/original/regraph \
  --production /home/chuxiao/grasu-regraph-complete-g \
  --output "$CAMPAIGN/fresh-k4-offline-control"
```

The service is limited to 4 GiB; each compiler/model child has a 2-GiB address
space and 120-second timeout. Shared original-R admission reserves complete
peer limits plus 24 GiB reserve and 8 GiB background; child launch independently
requires 32 GiB available reserve. `--wait-seconds`/`--poll-seconds` select a
finite memory queue, not a retry after failed execution. No board lease or
FPGA tool is used. `results.json` separates matrix completion, passing versus
unsupported row counts, memory events and false hardware/performance claims.

Before any later timing comparison, a separate board owner must admit the
FullPR xclbin, source/header closure, exact stream/CU/bank ABI, actual clocks
and global timing; obtain an exclusive BDF lease; restore all inputs between
repeats; check complete immutable/mutable buffers and guards; and measure
overlap-aware event union/span plus resident wall time. None of those gates
is satisfied by this CPU-only result.

## Full Board-Host Preflight

Add `--board-host-preflight` to the same study command with a fresh output.
This compiles the actual XRT-linked `control.cpp` in Release and UBSan,
records the resolved loader libraries and invokes only `prepare`, never
`board`. It keeps all 24 declared rows, the eight duplicate rejections and
the same independent CSR arithmetic. Every passing row exports complete
graph/state allocations under `expected_buffers/`, with bank, extent and
mutability metadata in `result.json`. Python checks exact file membership,
64-byte trailing canaries, bank capacity, raw/logical projection and hashes.
Complete targets and logical values must agree across both builds and both
repetitions; path-dependent provenance pins are not numerical comparisons.

Its distinct completion status is
`MATCHED_K4_A4_BOARD_HOST_PREFLIGHT_COMPLETE_NOT_FPGA_OR_PERFORMANCE_MATCH`.
Hardware, publication and performance assertions remain false. This prepares
the immutable expectations for a later board owner; it does not admit the
FullPR bitstream or claim that fabricated unit-test readbacks were measured.

The retained complete run is `original-r-k4-board-host-preflight-v2` under the
campaign root. All 24 rows completed: 16 prepared passes and eight unsupported
duplicate-edge rows; no errors or memory-limit/OOM events. Unit
`spine-original-r-k4-board-host-preflight-20261018-v2.service`, invocation
`4b3b7924eb3f42febbfadc6179d42350`, took 142.1 seconds and peaked at
1,527,021,568 bytes under a 4-GiB hard limit, 3584-MiB high limit, zero swap,
100% CPU, affinity 123 and `TMPDIR=/data/chuxiao/tmp`. The immutable runner
is `original-r-k4-host-runner-5ff46ab-v2`; archive SHA-256 is
`b3156b6c294bfd136a63081185bccba2602bc55243a1abc5e7e4cd4d204af48d`.
Result SHA-256 is
`0d8727fc5170280726613ba1d754809688552d5e690a04b3372917b47a385229`.
The preceding v1 service failed before Python package import because snapshot
extraction had not completed before permissions were restricted. It is retained
as a harness failure, not an executed matrix or a reason to change graph scope.

## Qualified Board Execution

`board_study` consumes that complete preflight, the immutable production
`sources.json` closure and one exact local FullPR-return service invocation.
It first independently rechecks all 24 prepared rows and full target files.
Without `--execute` it stops at `MATCHED_K4_BOARD_PLAN_RECHECKED_NOT_FPGA`:
no return service inspection, board reservation or device access occurs.
With `--execute`, a successful return is followed by fresh strict bitstream
ABI/clock/global-timing review, finite full-budget memory admission and an
exclusive board lease. A busy cooperating lease can wait up to 1800 seconds
before any programming; execution failures never trigger a reset or retry.

The board matrix retains all three graphs, both bindings and three repeats:
**18 rows**, including six explicitly unsupported `boundary_ring` rows and
twelve executable Amazon/`skewed_sources` rows. Each run uses a fresh process
and restores every graph/state buffer. Full raw buffers, canaries, external
projections, event dependency/overlap and resident wall time are rechecked by
Python independently of the host PASS string. The supervisor rechecks them
again before summarizing min/median/max. CPU fixtures test this orchestration;
they are not FPGA measurements or a performance match.

All 14 board-owner unit tests pass, including fabricated success/readback,
failed return/timing, timeout provenance, busy lease and invalid-time cases.
The complete 277-test original-ReGraph regression passed in 46.2 seconds,
peaking at 509.2 MiB in `spine-original-r-regression-20261018-v6.service`
(2-GiB hard, 1792-MiB high, zero swap, 100% CPU, affinity 123 and data-disk
temporary files). All 15 organization tests and document/catalog checks pass.
An initial organization-test invocation used the full host `/tmp` and failed
with ENOSPC; rerunning with `TMPDIR=/data/chuxiao/tmp` passes without deleting
others' files. No numerical/model/HLS changes are part of these tests.

Example prepare-only command, inside an 8-GiB hard / 7-GiB high / zero-swap
service with a fresh output, finite timeout and `TMPDIR=/data/chuxiao/tmp`:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.k4_control.board_study \
  --preflight "$CAMPAIGN/original-r-k4-board-host-preflight-v2" \
  --sources "$CAMPAIGN/production-algorithm-sources-v1" \
  --returned "$CAMPAIGN/production-fullpr-return-follow-v2" \
  --return-unit spine-production-fullpr-return-20261018-v2.service \
  --return-invocation 9f93433f962740e085a10b711c3394b4 \
  --device 1 --output "$CAMPAIGN/fresh-k4-board-plan"
```

Adding `--execute` requests actual device use; the unit/invocation and all
artifact identities must still match. The worker allows 600 seconds per run,
the supervisor bounds its complete process tree to 8 GiB and 11200 seconds,
and the memory queue accounts for full finite peer limits plus 24-GiB reserve
and 8-GiB background. Unknown/unbounded FPGA peers block new admission.

### Source-Version Boundary

The running FullPR route uses integration revision
`8e9ea1bb55ce3be16de543a32184efe07554b6a6`; the complete host preflight uses
`1a5650c79ae0c29418b93184a1590f256e33f0b6`. The graph/runtime-plan/l2 header
hashes are identical, but PageRank apply packing changed between revisions.
`source_contract` records both revisions and both apply hashes, checks the
complete sealed source closure, and does **not** claim source equivalence or
latest-revision performance. Independently passing every output can admit a
measurement of that specific routed revision only. The latest revision still
needs its own route and board measurements before it can label final figures.
Even a complete matrix is not default-profile, same-resource, host-inclusive,
convergence or original-publication equivalence: A4 uses fixed point, K4 uses
binary32, and their channel resources differ. Do not label their difference
as isolated adapter overhead.
