# Empty-Exit Model Control

## Conclusion

The generated RTL's 73-cycle empty-segment exit is now explicit in the
opt-in `grasu_regraph_routed_sssp_compute_v4` profile. It explains most of
the old adapter's missing empty-row cost in the fixed-payload control:
the four predicted adapter lifetimes differ from the existing FPGA medians
by -1.75% to +1.35%, versus roughly half the measured time before correction.
No coefficient was fitted to those board times.

**This is not complete adapter/ReGraph timing calibration or an A4 match.**
The optimized path skips these trailing empty rows; its predicted lifetime
remains 3.16 us against 84--94 us on the board. The remaining difference must
not be hidden by transferring the old path's local agreement to this path.
The full six-row real-graph replay and v4 matrix are the next gate, not part
of this sealed control checkpoint.

That subsequent gate is recorded in the separate
[real-graph matrix](../empty_exit_matrix/README.md): all six v4 results pass
full FPGA equality and all six v3 replays remain exact. Nominal timing is
closer on five rows; optimized WK and whole-path timing admission remain
open. The [occupied-row RTL follow-up](../occupied_row_rtl/README.md) also
checks why the 73-clock empty exit cannot be added after occupied output.
Neither follow-up replaces this control's frozen data or original claims.

## What Changed

The [generated-RTL experiment](../empty_row_rtl/README.md) observes 73 clocks
from helper start to done for every tested empty call, with no AXI requests
or edge transfers. The model now retires that control pipeline before
advancing to the next source. It charges only actually visited empty rows;
the optimized stop-after-last path still skips unused trailing rows.

The v4 profile retains v3's measured stream capacities and v2's independent
read/write directions. The memory model, clock, occupied-row issue schedule,
port topology and algorithm are unchanged. Earlier profiles default to zero
additional empty-exit cycles and keep their original results. This control
does not establish the exit timing of an occupied row.

## Fixed-Payload Results

All rows use the previous [four-size board control](../empty_rows/README.md):
the same live graph, post-update PMA, resident old state, one inserted edge
and two rounds. Only the unused source-ID tail grows. Board numbers are
medians of six adapter event lifetimes, two rounds in each of three runs;
model numbers are medians of the two modeled invocations. No new FPGA run
was performed for this replay.

| Vertices | Old adapter FPGA, ms | Old adapter v4, ms | Signed difference | Optimized FPGA, us | Optimized v4, us |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4,096 | 4.197153 | 4.123813 | -1.75% | 90.28 | 3.16 |
| 8,192 | 8.214282 | 8.247120 | +0.40% | 89.38 | 3.16 |
| 16,384 | 16.349262 | 16.493733 | +0.88% | 84.48 | 3.16 |
| 32,768 | 32.549211 | 32.986960 | +1.35% | 93.79 | 3.16 |

For each added empty row, the old model adds 520 ns; v4 adds 1,006.67 ns,
versus 980.74--993.04 ns in the board's adjacent-size differences. The
new slope is 1.37--2.64% above those observations. These are descriptive
differences, not a fit or a predeclared whole-system acceptance threshold.

Adapter event lifetimes include stream backpressure. Modeled invocations
exclude host/XRT dispatch and use assumed memory addresses/timing; they are
not an exclusive FPGA pipeline counter. The small optimized case especially
cannot identify the missing time as memory, host or compute without further
evidence. Kernel lifetimes must not be summed as serial stages.

## Verification And Evidence

- Fresh Release core build and all 23 CTest targets pass. The adapter tests
  include 576 old/new component pairs with unchanged packet words and
  conserved requests; each added delay equals 73 times visited empty rows.
- Five full legacy SST results remain exactly equal, with no ignored fields.
- Eight v2 sweep replays preserve every result field and full output bytes.
- Eight v4 executions preserve full FPGA output, convergence, source replicas
  and non-timing traffic counters. Every final run uses one frozen plugin
  and source identity; the default installed plugin is untouched.
- The 126 focused Python gates pass. Three additional portable-package tests
  recheck archive hashes, dependencies, full outputs, sources and timing.

The sealed [report](model.json) and [raw index](model_raw_index.json) identify
`raw_model.tar.gz`. It contains source snapshots, the tested plugin, build
flags, input fixtures, all 16 sweep runs, legacy results and command/resource
logs. Dependency indexes link the unchanged board, RTL and v3 evidence.
Experiment code is owned by `sharded_k4_stages/row_exit_contract.py`,
`row_exit_sweep.py` and `row_exit_delivery.py`, not another versioned runner.

## Reproduction

Use a new output directory and a fresh plugin built from the archived source.
The recorded campaign root is
`/data/chuxiao/experiments/sharded_k4_empty_exit_model_20261011`.
The exact build and regression commands are in `model.json` under
`verification`; the sweep command is archived in
`campaign/sweep_run.resources.json`. The latter calls `replay_sweep` with the
frozen board-control directory, exporter and explicit plugin directory.
Each child has an 8-GiB limit with a 16-GiB memory reserve. Legacy regression
uses at most two workers; sweep runs are sequential.

Portable verification, from the repository root:

```bash
python3 -m unittest tests.test_sharded_k4_row_exit \
  tests.test_sharded_k4_row_exit_delivery \
  tests.test_sharded_k4_empty_exit_package
```

Next, run the complete `sharded_k4_routed_sssp_timing_v4.json` contract and
an exact v3 replay before evaluating the real-graph timing change. Preserve
any residual mismatch, then resolve occupied-row/source/transport scheduling
and the original-A4 algorithm/resource/window differences. This checkpoint
does not change paper figures or admit a publication-speed comparison.
