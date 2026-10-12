# Continuous Directory Candidate: Rejected

## Decision

**Do not promote this candidate or quote its nominal model speedup.** The
default-off single-loop reader preserves complete results, packet contents and
physical traffic, but its production HLS achieves initiation interval (II) 71,
not the requested II 1. Its estimated clock period is 13.845 ns against the
6.67-ns target. Nine of twelve synthetic RTL cases regress. No route or board
run was attempted for this rejected candidate.

This is a completed candidate investigation, **not completion of the goal of
bringing actual adapter+K4 performance close to original A4**. The default
simulator/HLS modes, historical bitstreams and paper are unchanged. Start with
the [previous original-A4/V3 control](../cross_row/a4_control/README.md) for the
still-valid model baseline.

## What Changed

V3 caches eight row descriptors and pipelines PMA reads within that block,
then drains the occupied-block reader before loading the next directory line.
The candidate tries to combine directory, source and segment traversal in
one loop on the same AXI master, without the per-block drain.

The corresponding explicit simulator option bypasses that drain while
retaining finite request capacity, loaded FIFO, read latency and backpressure.
It is now labeled a **counterfactual schedule**, not an implementation-matched
timing model: synthesis exposed a memory dependency in the single-loop HLS.
Correctness and conserved traffic do not validate an unrealized II=1 schedule.

The option is off by default and is not added to production SST profiles.
It has no timing multiplier, free sparse-source index, new external port,
unaccounted state replica or change to PMA padding/edge storage.

## Model Control

The immutable input is the earlier Amazon structural control: 258,046 vertices,
1,450,899 edges, four destination partitions, original physical IDs retained.
Both arms perform **one resident synchronous SSSP round**, not convergence.
Warm input starts from the independently converged old state with three weight
decreases and source reactivation. Cold input is separately labeled. GraSU
updates, preparation, DMA, launch and host orchestration are outside this window.

The complete matrix has three arms, two registration orders and three
mode/latency pairs: cold/64, warm-update/64 and warm-update/128. All 18 runs
pass complete-state/replica and physical-work checks; old A4 and V3 replay
their frozen counters, cycles and invocation schedules exactly. Both orders
match and increased memory latency increases candidate cycles.

| Warm input, model memory latency | Original A4 | V3 | Counterfactual candidate | Candidate / A4 |
| --- | ---: | ---: | ---: | ---: |
| 64 cycles | 668,278 | 5,310,204 | 2,932,008 | 4.39x |
| 128 cycles | 1,292,225 | 9,382,727 | 5,094,203 | 3.94x |

The candidate's nominal 1.81--1.84x improvement over V3 is **not admitted**.
Even that unrealized schedule does not reach A4 parity. Cold and warm rows
have equal cycles in this full-scan, fixed-round model; this is not a claim
that warm/cold convergence costs are equal.

This is an original-topology control, not strict resource equivalence. Original
A4 and actual K4 differ in master organization, state replicas, queue budgets
and layout; four frontends alone do not establish resource equality. Keep the
[earlier resource inventory](../cross_row/a4_control/README.md) with the result.

## Actual HLS And RTL

Production compile uses U55C/150 MHz, Vitis 2024.1, the unchanged V3 flags plus
`GRASU_REGRAPH_CONTINUOUS_DIRECTORY=1`. Complete kernel XML/control/master/stream
ABIs match. The source remains in the integration repository, under
`kernels/pma_to_regraph_adapter/continuous_directory.hpp`.

| Synthetic trial | V3 RTL clocks | Candidate RTL clocks |
| --- | ---: | ---: |
| 0 | 6 | 12 |
| 1 | 232 | 230 |
| 2 | 267 | 1,224 |
| 3 | 396 | 1,437 |
| 4 | 560 | 2,644 |
| 5 | 588 | 2,728 |
| 6 | 1,036 | 4,072 |
| 7 | 730 | 5,278 |
| 8 | 402 | 392 |
| 9 | 244 | 242 |
| 10 | 416 | 1,461 |
| 11 | 1,080 | 2,728 |

Each arm passes all twelve full-top AXI simulations, including response-latency,
placement, row-tail and sink-backpressure controls. All packet data/keep/strb/last
values, row/PMA transfer counts and response conservation agree. Trial shapes
and full handshakes are in the raw traces. These are synthetic adapter RTL
clocks, not HBM-calibrated cycles or real-graph FPGA performance.

The nested `read_continuous_sources_loop` report exposes II=71 and depth=74;
the top-level report's loop list is empty and alone would miss this failure.
Estimated resources are 31,638 LUTs, 9,741 FFs, 15 BRAM_18K, zero DSP/URAM.
These synthesis estimates do not establish routed timing or area/energy claims.

## Review And Reproduction

| Item | Location |
| --- | --- |
| Recomputed rejection and regression summary | [results.json](evidence/results.json) |
| Archive identities and complete member index | [verification.json](evidence/verification.json) |
| Executed sources, inputs, all states, binaries, XOs, RTL, schedules and logs | Lossless raw archive parts, indexed in [verification.json](evidence/verification.json) |
| Code owner | `spine_cycle_sim/experiments/sharded_k4_stages/row_line/continuous_directory/` |
| Focused admission tests | `tests/test_sharded_k4_continuous_directory.py` |

The package separates execution (`study.py`, `hls.py`), numerical checks
(`analysis.py`), schedule admission (`decision.py`), portable raw revalidation
(`recheck.py`) and packaging (`delivery.py`). Executed source archives are
immutable; post-run review code is separately labeled in the archive.

Regression passes 406 sharded-K4, 120 original-ReGraph and 44 refactor tests;
the fresh complete core build passes 27 tests, and all five SST cases replay
their full payloads, cycles and traffic exactly. A later 26-test focused gate
checks archive transport and the explicit frozen-source resource audit (it
overlaps the larger suites). These checks do not admit the candidate's timing.
The default plugin retains SHA-256
`9a26e1fb51ecf7b99ccf0784c9e5bbc459cf857d293add557b9c52770b2c9d79`.

The archive is transported in at most 64-MiB parts because its complete raw
evidence exceeds GitHub's single-file limit. `archive_parts.py` checks each
part and the reassembled archive hash before the existing safe extraction
and raw recheck. No log, source snapshot or negative result is omitted to
reduce upload size. The CLI reassembles automatically in a temporary directory.

From the simulator root, verify the bundle without original run paths:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.continuous_directory.delivery \
  --destination docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/continuous_directory/evidence \
  --verify-only
python3 -m unittest tests.test_sharded_k4_continuous_directory
```

For a fresh model study, call `continuous_directory.study --basis OLD_A4_V3_RUN
--output FRESH_DIRECTORY`. For HLS call `continuous_directory.hls --integration
INTEGRATION_ROOT --reference V3_ADAPTER_XO --output FRESH_DIRECTORY --vivado-bin
/data/yxx/tools/xilinx/Vivado/2024.1/bin`. Historical source/build/input identities
are in the archive; rerunning later worktree code is a new experiment.

All executions preserve a 16-GiB available-memory reserve and bounded process
tree RSS/time. The model build is limited to two jobs/6 GiB; synthesis to
8 GiB/1,200 seconds; each RTL step to 4 GiB/120 seconds. The evidence retains
the initial full-suite invocation that found missing executables in the
EXCLUDE_FROM_ALL harness; a separate fresh root build is the complete test gate.
It also retains the earlier Python-suite source-pin rejection: the historical
resource audit now explicitly uses its hash-checked archived source, while
the default live-source audit still rejects unreviewed drift. Neither its
old pins nor its resource inventory was replaced.

## Next Gate

Test a bounded directory tile or separate directory prefetch/control from the
edge-read pipeline. First prove the actual HLS schedule and complete RTL
correctness, then implement that exact finite organization in the simulator.
Account for caches, extra directory work, empty tails and FIFO/backpressure.
Do not assume that removing block drains alone can match A4: padded PMA
input in this fixture is still about 5.24x the compact input. A layout or dummy
filtering optimization would need its own measured cost and correctness gates.
