# Matched Adapter/K4 And Original A4

This CPU-only preparation and one-superstep value model is not a cycle model,
device execution, HLS simulation, board admission, or a performance result.
It does not extend the original R model or change production code.

## Interface

```text
original_r_k4_model control INPUT author_initial|csr_degree OUTPUT
```

`INPUT` is an admitted original R A4 directory with `execution.u32le`,
`tasks.u32le`, `initial.u32le`, `degrees.u32le`, `csr_offsets.u32le`, and
`csr_destinations.u32le`. Files must be regular and not symlinks. The original
guarded loader and its signed-arithmetic/capacity checks remain authoritative.
Output must be a fresh directory with an existing parent. Failures return 1;
only successful validation produces `result.json`. Partial output after an I/O
failure is not a passing result. Concurrent writers must not share OUTPUT.

Output schema version 1:

| File | Exact contents |
| --- | --- |
| `gathered_external.u32le` | V raw binary32 words: incoming CSR gather / expected next rank, external ID order |
| `payload_external.u32le` | V raw binary32 words: expected published next-source payload, external ID order |
| `external_to_internal.u32le` | V unsigned production permutation indices, not float bits |
| `result.json` | Schema/status, binding/geometry/profile, explicit offline assertions and no-hardware claims |

The JSON status is `OFFLINE_MATCHED_K4_A4_MODEL_PASS_NOT_FPGA`.
`vertices`, `logical_edges`, `a4_published_vertices`, `capacity_vertices`,
`partitions`, `partition_vertices`, `graph_channels`, `cache_segments`, and
`row_line_read` describe geometry. `iterations`, damping numerator/denominator,
`base`, `dangling_share`, `rank_initial`, `updates`, `g_skipped`, and
`source_prepare_skipped` describe the controlled profile. `assertions` contains
`csr_task_edges_equal`, `permutation_bijection`, `pma_conservation`,
`packed_gather_equal`, `full_capacity_and_trailing_guards`, and
`guarded_bank_capacity`. All must be true. `board_programmed`,
`hardware_timing_measured`, `publication_match`, and
`default_profile_equivalence` are false. Binary encoding fields name the
formats in the table. No hash or timing is manufactured; orchestration may hash
the exact files against its independent arithmetic audit.

`model.hpp` exports `original_r_k4::Model::load(path, Binding)`.
`Binding` aliases `original_r_board::Binding` and has no default CLI binding.
The model exposes `original` (A4 fixed-point oracle/guards), `preparation.graph`
(including both permutation maps), `preparation.plan` (unmodified production
placement), `preparation.buffers`, `preparation.ledger`, `state`,
`worker_partitions`, and logical external gather/payload/fixed vectors.
`Buffer.initial` and `Buffer.target()` include the full allocation plus guards;
`Buffer.verify(actual)` checks exact equality including allocation slack and
canaries. An empty `expected` means read-only with target equal to initial.
Graph buffer names match production region names and have a shard ordinal;
state names are `source_a0`, `source_a1`, `source_b0`, `source_b1`, `rank`,
`divisor`, and `stats`, with `no_shard`. PMA words are dst19/weight12 integers;
row/binary/update uint64 values are low-word then high-word. State divisor and
stats counters are integers, while source/rank and stats slots 2/3 are float bits.
Only stats slots 0--4 are written; all other stats words remain canaries.
These CPU vectors are not pinned or guaranteed 4096-byte host alignment;
future device code must provide its own suitably aligned owning allocations.

## Contract And Rejections

Production `weighted_pma_graph.hpp` and `weighted_pma_runtime_plan.hpp` are
included directly through `-I/home/chuxiao/grasu-regraph-complete-g/include`.
The exact builder receives static unit-weight CSR edges and empty updates.
Its permutation is checked as a bijection with an exact inverse; source,
divisor, and gather are all remapped. Duplicate CSR or task edges are rejected,
never silently deduplicated. Task/CSR edge identity is checked in addition to
their gathers, so equal-valued sources cannot conceal a changed graph.

Every decoded PMA row/edge/head and packed port is checked, including empty
segments and unused cache/DDR slots. Runtime planning uses 23 graph channels,
lane-aware U55C placement, cache 131072, row-line reads, and 65536-vertex
partitions, including an empty final partition if the vertex extent needs it.
The two source ping-pong pairs use banks 23/24; rank uses 25; divisor and stats
use 27. Every production graph allocation retains its 4096-byte allocation
extent and receives another 16-word trailing guard. State covers every full
destination partition plus the same guard. Allocation slack uses the canary;
logical PMA empties use the production sentinel. Bank accounting includes all
resident buffers and guards, rejects buffers >=256 MiB or aggregate banks
>512 MiB, and does not re-place a plan that guards make inadmissible.

The incoming source is the admitted initial integer property, exactly converted
to binary32, not production's prepared damped rank/outdegree source. Rank starts
at zero. The unchanged FullPR mode-1 apply is modeled at damping 108/128,
base=0, dangling_share=0, one step: rank=incoming; payload=round32(
round32(damping*rank)/divisor), or zero for divisor zero. All real vertices are
active, including zero-valued and dangling vertices. Padded rank stays zero;
published source padding becomes zero. Stats reproduce the apply's 16-lane,
eight-bank reduction order. No G/update or source-prepare kernel is modeled as
executed. Source B starts as canaries to expose incomplete publication.

Independent CSR gather uses uint64 sums, checks the original signed arithmetic
for the chosen binding (and inherits the loader's CSR-degree check), then
rejects any gather above 2^24. Nonnegative unit-weight partial sums are therefore
exact binary32 under any gather order. Source/divisor conversions must be exact;
signed damping/product overflow, malformed CSR/permutation/rows, non-unit
weights, PMA edge loss/duplication, and guarded capacity overflow all fail closed.
IEEE binary32, round-to-nearest, no fast-math and no contraction are required.

Original A4 stores a truncated signed fixed-point apply result; K4 rank is the
undamped gather and K4 source payload is binary32. These are distinct outputs,
not bitwise equivalents. A4 may publish only a prefix (`skewed_sources` does),
leaving an untouched sentinel tail, while K4 covers its full partition capacity.
The controlled initial state, damping, base, dangling policy, skipped G/source
prepare, and finite one-step boundary differ from the default production host's
PageRank profile. No convergence/default/publication equivalence is asserted.

## Build And Focused Tests

Compile `offline.cpp` as C++20 with `-O2 -DNDEBUG -fno-fast-math
-ffp-contract=off` and the production include path above. The focused Python
test compiles both this CLI and `model_tests.cpp` in Release and UBSan variants,
uses tiny corruption fixtures plus the exact admitted `skewed_sources` and
`boundary_ring` directories, and independently checks external float bits.
It never loads Amazon automatically or runs a six-layout matrix.

The exact admitted root is
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/original-r-control-validation-v4/inputs/a4`.
`skewed_sources` is the passing control for both bindings. `boundary_ring`
contains 64 duplicate CSR records (first repeated external edge 352 -> 43409)
and must be rejected for both bindings; tests independently verify this input
limitation rather than changing it or treating it as a passing PMA control.

All compiler and test children must inherit finite cgroup limits. From the
repository root:

```bash
systemd-run --user --wait --pipe --collect \
  --property=MemoryMax=2G --property=MemoryHigh=1792M \
  --property=MemorySwapMax=0 --property=OOMPolicy=kill \
  --property=CPUQuota=100% --property=CPUAffinity=123 \
  --property=RuntimeMaxSec=180 \
  --working-directory="$PWD" \
  /usr/bin/python3 -m unittest discover -s tests \
  -p test_original_regraph_k4_model.py -v
```

Verification on 2026-10-18: unit `original-r-k4-focused-20261018-d.service`
completed successfully. All five focused unittest methods passed in 22.074 s
(service runtime 22.178 s, cgroup memory peak 384.6 MiB). Both C++ translation
units compiled in Release and UBSan with warnings as errors. The cgroup used
the exact limits above, plus `KillMode=control-group` and `TasksMax=128`.
`skewed_sources` passed both bindings in both builds, checked against independent
Python CSR sums, binary32 payload bits, and the production reorder rule.
`boundary_ring` was independently counted and rejected for its 64 duplicate
records in both bindings/builds. Synthetic tests covered both bindings, exact
nonidentity remapping, signed/float admission failures, edge/permutation/PMA
corruption, row-line padding, unused cache slots, full state tails/canaries,
bank accounting/overflow, input symlinks, and output overwrite refusal.
Those focused tests used cleaned-up temporary outputs, not retained board
evidence. The separate retained 24-row offline study subsequently completed:
Amazon (735324 vertices, 5158388 edges) and `skewed_sources` each pass all eight
build/binding/repetition combinations; all eight `boundary_ring` combinations
remain unsupported for their duplicate records. See the
[study checkpoint](../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/k4_control/README.md#retained-offline-result)
for paths, hashes, the retained first harness failure and exact scope. This is
not a passing three-graph FPGA or performance matrix.

## Guarded Board-Host Components

| File | Responsibility |
| --- | --- |
| `schedule.hpp` | Exact production producer/consumer ordering, idle workers, per-worker partition reuse and event-dependency validation |
| `device.hpp` | Explicit XRT buffers and kernel arguments, out-of-order profiled queue, event union/span and complete raw buffer readback |
| `report.hpp` | Separate preparation, executed-but-unverified and guarded-board-pass reports |
| `control.cpp` | Thin explicit `prepare`/`board` command interface |
| `schedule_tests.cpp` | Pure CPU schedule/dependency and overlapping-event checks |

```text
original_r_k4_control prepare INPUT author_initial|csr_degree OUTPUT
original_r_k4_control board INPUT author_initial|csr_degree OUTPUT XCLBIN DEVICE
```

`prepare` does not create a device context or program a board. It writes
`expected_gather.u32le`, `expected_payload.u32le`, the permutation and a
`K4_BOARD_HOST_PREFLIGHT_PASS_NOT_FPGA` report. Timing fields are null,
events are empty and all hardware assertions are false. The board mode
requires the external exclusive lease and expected BDF; it is not a substitute
for the independent bitstream qualification below.

The board mode restores every graph/state buffer from the model before the
run. HBM/apply consumers and every adapter/gather/mux command are submitted
before waiting, using the production per-worker and shared-mux dependencies.
Resident wall time covers argument binding/enqueue through completion;
allocation, upload, preparation and readback are excluded. Complete raw
readbacks are saved under `readback/` before verification. The external gather
and payload files come from actual rank/source-buffer readbacks, not the
expected vectors. Full graph and state allocations, slack, tails and guards
must pass before status becomes `MATCHED_K4_A4_GUARDED_BOARD_CONTROL_PASS`.
Three repetitions must still be independently scheduled by the board owner.

`board_build.py` owns explicit Release/UBSan XRT build commands. Six focused
Python tests compile the real host and schedule tests in both variants and
check synthetic and exact `skewed_sources` preparation, independent CSR
arithmetic, output refusal, duplicate rejection and no-lease rejection before
context/programming. Unit `spine-k4-board-host-tests-20261018-v1.service`
passed in 20.1 seconds with a 513.4-MiB peak under the same finite 2-GiB,
zero-swap, CPU-123 limits used above. These tests never programmed an FPGA.

```bash
systemd-run --user --wait --pipe --collect \
  -p MemoryMax=2G -p MemoryHigh=1792M -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p CPUQuota=100% -p CPUAffinity=123 -p RuntimeMaxSec=180 \
  -p TimeoutStopSec=15 -p KillMode=control-group -p TasksMax=128 \
  --working-directory="$PWD" /usr/bin/python3 -m unittest discover \
  -s tests -p test_original_regraph_k4_board_host.py -v
```

## Remaining Board Gates

The offline model API is preparation only. A board owner must separately admit the
actual routed identity (FullPR mode 1, row-line adapter/K4 connectivity and
23-channel lane ranges), source/header and xclbin hashes, memory placement,
all stream ABI/kernel signatures, SLR/frequency/route closure, and exclusive
device lease/BDF with reset/recovery policy. Do not run on an unmatched xclbin
or treat a successful offline assertion as satisfying those gates.
The C++ host implements the execution and readback operations above, but its
CPU tests do not validate them on a device. Python route qualification,
independent board-readback analysis, complete repeated execution and failure
recovery remain separate gates; no actual adapter/K4 FPGA timing is available.

Source owners: original `hardware/model.hpp` and `whole_graph/input.hpp`;
production `include/weighted_pma_graph.hpp`,
`include/weighted_pma_runtime_plan.hpp`,
`tools/sharded_k4_pagerank_native_host.cpp`, and
`kernels/regraph_pagerank_apply/regraph_pagerank_apply.cpp` in the clean
production repository. The offline model/schedule tests need no vendor
runtime; only the guarded board host requires OpenCL/XRT.
