# Original ReGraph Versus A4: Board Comparison

## Decision

Both controls have completed their full declared U55C matrix: three graphs,
two explicit divisor bindings, three repetitions, at an implemented 150 MHz.
An independent replay checks all raw output replicas, padding, guards,
mathematical oracles, frozen inputs, runtime and strict routed timing before
forming the ratios below. This is a measured topology control, **not yet a
performance result for the latest adapter + sharded K4**.

On Amazon, A4 takes 1.059--1.083 times the original 11+3 device event span.
Its resident wall time is only 0.556--0.575 times the original. The opposite
directions are possible because the wall window also includes argument
binding, enqueue and queue completion, which differ between these topologies.
Neither window is a substitute for the other.

## Complete Results

Times are medians of three runs. Ratios are A4 time / original 11+3 time;
less than one means A4 is faster. Event union and span coincide in these runs.

| Graph | Divisor binding | 11+3 wall ms | A4 wall ms | Wall ratio | 11+3 event span ms | A4 event span ms | Span ratio |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| boundary_ring | author_initial | 8.171378 | 2.049860 | 0.251 | 1.231156 | 1.289567 | 1.047 |
| boundary_ring | csr_degree | 8.062894 | 2.072270 | 0.257 | 1.188865 | 1.362780 | 1.146 |
| skewed_sources | author_initial | 2.297357 | 0.948728 | 0.413 | 0.674320 | 0.442593 | 0.656 |
| skewed_sources | csr_degree | 2.206814 | 0.936078 | 0.424 | 0.524605 | 0.435953 | 0.831 |
| amazon | author_initial | 22.816932 | 12.687600 | 0.556 | 9.563118 | 10.129416 | 1.059 |
| amazon | csr_degree | 21.814873 | 12.538786 | 0.575 | 9.228968 | 9.996112 | 1.083 |

`boundary_ring` has 131,073 vertices / 131,137 edges; `skewed_sources` has
65,537 / 8,193; Amazon has 735,324 / 5,158,388. IDs are not compacted.
Both paths use one static signed fixed-point PR superstep, `arg=0`, with
identical CSR, initial state and divisor arrays for each paired row. Logical
outputs match across topologies. `author_initial` and `csr_degree` deliberately
test different apply divisors; they are not pooled as repetitions.

## Scope And Limitations

The resident wall window starts before argument binding/first enqueue and
ends after all queues finish. It excludes input preparation, programming,
DMA and readback. The device event span runs from the first event start to
the last event end. Overlapping events are not added.

Both controls use the same Release host, CPU affinity, board, driver and
loaded runtime libraries. Original 11+3 retains its larger publication extent
and distinct task schedule. A4 uses the author's nine-bank layout, not the
actual K4/23-channel layout. Four Little pipelines do not by themselves mean
equal resource budgets.

Consequently these data do not establish publication-speed reproduction,
latest K4 performance, adapter overhead, convergence, host-inclusive dynamic
latency or a Spine speedup. The separate
[actual K4 candidate](../k4_control/CURRENT_CANDIDATE.md) still needs its own
matched board result. The old A4/PMA simulator slowdown is not substituted.

## Evidence And Reproduction

Raw root: `/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.

| Record | Directory / report | SHA-256 |
| --- | --- | --- |
| Original 11+3 matrix | `original-r-board-supervisor-v4/board/results.json` | `00b8403b21a829c011c3facfd921587fee0931ca641dc444315c2ae63c4e95b4` |
| A4 matrix | `a4-board-supervisor-v3/board/results.json` | `d5386df1306c0084840348ece4ba748fe6a528307f67a3f15f3423ac13f8dfab` |
| Replayed comparison | `original-r-a4-measured-comparison-v1/results.json` | `989f04f77e7cf67e393e4bd13cd7304cd248a46b5cdc087d076501216d17c2c3` |

The comparison JSON retains all six min/median/max summaries, exact logical
input/output hashes, runtime identities, source-report identities and external
hash pins. The original [portable board capsule](../board_matrix/README.md)
retains the original matrix and failed startup attempts. No frozen result was
rewritten by this comparison.

From the repository root, use fresh output names:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution.comparison \
  --original /data/chuxiao/experiments/baseline_hardware_validation_20261015/original-r-board-supervisor-v4 \
  --a4 /data/chuxiao/experiments/baseline_hardware_validation_20261015/a4-board-supervisor-v3 \
  --output /data/chuxiao/experiments/baseline_hardware_validation_20261015/original-r-a4-measured-comparison-fresh
python3 -m unittest discover -s tests -p test_original_regraph_board_comparison.py
```

The offline replay took 8.656 seconds with a 148.4-MiB cgroup peak, under
4-GiB hard / 3-GiB high / zero-swap containment and CPUs 124--125. This is
analysis cost, not an FPGA timing observation. The six new comparison tests
and all 37 board-control tests pass, as do fifteen organization tests,
document-layout/catalog checks and `git diff --check`. Those fixture tests
are not additional FPGA executions. Numerical simulator/HLS code is unchanged;
no new core, SST or hardware run is claimed by this offline aggregation.
