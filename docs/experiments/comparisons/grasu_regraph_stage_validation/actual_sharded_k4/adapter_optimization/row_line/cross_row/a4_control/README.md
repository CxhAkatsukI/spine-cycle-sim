# Cross-Row Input Versus Original-Style A4

## Decision

All 18 predeclared resident-round runs pass complete-state and conserved-work
checks. Original A4 and the previous whole-line K4 reproduce their frozen
cycles, counters and invocation traces exactly. Cross-row K4 improves
predicted time by 3.26--3.28x versus whole-line K4, but still takes
**7.26--7.95x the original-A4 cycles**. The negative result is retained.
This is not FPGA timing, a publication match, an isolated adapter overhead
or completion of the overall performance-validation objective.

| Resident scenario | Memory latency | Original A4 cycles | Whole-line K4 cycles | Cross-row K4 cycles | Whole-line/cross-row | Cross-row/A4 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Cold source, one round | 64 | 668,278 | 17,326,124 | 5,310,204 | 3.263x | 7.946x |
| Warm update, one round | 64 | 668,278 | 17,326,124 | 5,310,204 | 3.263x | 7.946x |
| Warm update, one round | 128 | 1,292,225 | 30,796,315 | 9,382,727 | 3.282x | 7.261x |

Each displayed row is repeated with reversed component registration; every
cycle, counter, invocation and output remains identical. Cold and warm
states differ, although their one-round work and cycles coincide. No
acceptance criterion requires the candidate to be faster.

## Scope And Interpretation

The pinned Amazon input has 258,046 vertices, 1,450,899 directed edges,
sixteen author-style A4 tasks and four destination-sharded PMAs. External
IDs 1--258,048 are selected before author DBG processing; holes are not
silently compacted. Weights are a positive 12-bit overlay. The warm arm
starts from the same old converged distances and reactivated source in both
paths after three source-0 weight decreases. It is still **exactly one
synchronous round**, not propagation to convergence or the hardware Figure 7
experiment. The cold control does not stand in for a warm measurement.

Inputs and state are resident. Timing starts at the first component tick
and ends after all state-write acknowledgements. GraSU updates, preparation,
DMA, host launch/wait and inter-round orchestration are excluded on both
sides. This comparison contains no measured host or GraSU time.

Memory is the unchanged fixed MockMemoryBackend: 150 MHz, 32 channels,
one issue per channel per cycle and 32 outstanding/response credits per
channel. Latencies 64 and 128 are sensitivity settings, not DRAMSim3 or
measured HBM latency. The adapter also retains its inherited 71-cycle
minimum issue-to-use floor. No parameter was fitted to the new results.

This harness uses the actual adapter and modified K4 **numerical components
and PMA layout**, not an exact replica of the routed 23-channel system.
Original A4 has thirteen logical AXI masters, four state copies and shared
read/write credits; this K4 control has nine masters, three state copies plus
status, two source-state masters and independent read/write credits. The
cross-row profile pins the candidate's implementation identity; it does not
turn these harness resources into the routed hardware resources. Four
frontends alone do not establish a strict resource match.

The candidate preserves all whole-line traffic: 129,022 directory reads,
475,612 segment reads, 951,224 output packets, 6,158,893 dummy edges,
43,939,712 read bytes and 3,145,732 write bytes. Each of its three output
replicas has 262,144 checked words and equals the complete frozen oracle.
Thus this improvement comes from changed scheduling/overlap, not omitted
edges, free repacking or reduced state publication.

At latency 64 all four adapters start at cycle zero and finish at
5,168,603 / 5,115,088 / 4,977,651 / 4,355,338. The last gather finishes at
5,309,621; completion including remaining acknowledgements is 5,310,204.
These overlapping lifetimes do not isolate exclusive stalls. Physical PMA
slots remain 7,609,792 versus 1,451,712 compact A4 entries. Padding, directory
block boundaries and backend scheduling remain investigation targets;
this report does not assign the remaining 7--8x difference to any one cause.
The inherited static layout audit describes the historical sequential
adapter assumptions, not a new cross-row runtime stall decomposition.

## Reviewable Ownership

The only changed pre-existing numerical file is
`cpp/tests/routed_regraph/round_execution.hpp`: a default-off option selects
the already separately owned cross-row adapter. Older three-field option
initializers retain their behavior. The thin CLI is
`cpp/tests/routed_regraph/cross_row/round.cpp`; the original A4 executable,
production components, both production build lists and default SST plugin
are not changed by this control.

The Python owner is
`spine_cycle_sim/experiments/sharded_k4_stages/row_line/cross_row/a4_control/`:

| Module | Responsibility |
| --- | --- |
| `contract.py` | Exact historical/source identities, six scenarios, three arms and limits |
| `preparation.py` | Recheck the previous raw package; freeze complete inputs, oracles and sources |
| `execution.py` | Fixed compiler, fresh build, affinity and bounded commands |
| `analysis.py` | Exact reference replay, candidate state/traffic and complete matrix gates |
| `study.py` | Bounded orchestration and source/tool/plugin preservation |
| `recheck.py` | Independently recompute the conclusion from relocatable raw files |
| `delivery.py` | Seal and recheck one immutable portable package |

Before the harness edit, 358 source files were archived with SHA-256
`5fb7b23690ed312d86057b2c36dcebbbfd02a277d923fe23bdf3c56d91743478`.
The run freezes 736 executed source/configuration/test files and explicitly
declares that single pre-existing harness change. The previous A4 report
remains pinned to
`a24a3543ad12abd72c7dc92d9e85dbf3f6c9444f35b8f56751b768eb8f4b249f`.
Its package and validator are not rewritten or relaxed.

## Artifacts And Reproduction

| Artifact | Contents |
| --- | --- |
| [Results](evidence/results.json) | All 18 runs, complete states, counters, invocations and explicit non-admissions |
| [Verification index](evidence/verification.json) | Raw file hashes, archive identity and aggregate watchdog |
| [Portable raw archive](evidence/raw_cross_row_A4.tar.gz) | Frozen sources, profiles, inputs, oracles, outputs, executables/build flags, pre-edit snapshot, historical bases and raw logs |
| [Regression index](regression.json), [raw regression archive](raw_regression.tar.gz) | Additional portable/tamper tests, complete suite transcripts and sampled resource records |

The numerical archive contains 932 files, is 57,056,610 bytes and has SHA-256
`6d297e0df42ca4c7b2445caadd857830bceb6b0012e46333b6e744388569cb3b`.
Its independently extracted recheck passes. The final regression passes 379
sharded-K4 tests, 120 original-ReGraph tests and fifteen structure tests.
Sixteen focused tests include seven checks against this actual raw package:
altered reference cycles, candidate traffic, full output state, executed
source and sealed summaries are rejected. These later tests and their logs
are sealed separately; the original numerical snapshot is not rewritten.

Portable verification needs no FPGA, proprietary tools or original external
paths. Run from the simulator repository root:

```bash
D=docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/cross_row/a4_control
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.a4_control.delivery --destination "$D/evidence" --verify-only
python3 -m unittest discover -s tests -p 'test_sharded_k4_cross_row_a4*.py'
```

For a fresh execution, extract the archived pre-edit snapshot and its
adjacent `pre_edit_source_index.json`, then use new output paths:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.a4_control.study \
  --output /absolute/path/to/fresh_cross_row_A4 \
  --pre-edit /absolute/path/to/pre_edit_source.tar.gz
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.a4_control.delivery \
  --run /absolute/path/to/fresh_cross_row_A4 \
  --destination /absolute/path/to/fresh_delivery
```

Fresh execution requires the pinned previous whole-line A4 package in this
repository, GCC 15.2.0 at `/usr/bin/g++`, CMake and CPUs 112--113. Builds use
two jobs; numerical runs are serial. Each child has 180 seconds, 3-GiB
sampled tree RSS and a 16-GiB live reserve. The aggregate watchdog has
1,800 seconds and 8 GiB with the same reserve. The completed campaign took
382.11 seconds, with aggregate peak sampled RSS 819.45 MiB and minimum
available memory 33.92 GiB. Sampled pidfd cleanup is not cgroup containment.

## Remaining Gates

1. Retain this negative result while identifying remaining costs; do not
   remove padding or directory work from the model without matching HLS.
2. Route the production V3 XO and measure paired board results when the
   unchanged 40-GiB job plus 16-GiB reserve is available. The current model
   ratio is not an FPGA slowdown or speedup.
3. Resolve the resource, memory and event-window differences before a
   stronger A4/K4 comparison. Original-publication reproduction, isolated
   GraSU performance and full update-to-convergence remain separate gates.

The paper, figure handoff and historical evidence are unchanged. Read the
[model checkpoint](../model/README.md) for legacy SST/core gates and the
retained synthetic timing failures.
