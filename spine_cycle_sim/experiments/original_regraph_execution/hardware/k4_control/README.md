# Matched Adapter/K4 Offline Control

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
model tests passed for `skewed_sources`; Amazon has not yet been admitted at
this implementation checkpoint. The complete study result, not these tests,
determines the available comparison scope.

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
