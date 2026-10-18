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
| `study.py` | Full-budget atomic admission, bounded compilation/execution, records, failure retention and unchanged closure |

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

The host preserves full raw readbacks and only promotes executed/unverified
to guarded-pass after exact buffer checks. Python route/ABI qualification,
independent raw-readback analysis and repeated board execution remain pending.
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
