# Controlled Empty-Row Diagnostic

## Conclusion

The complete predeclared control passes: **24 FPGA runs and eight fixed-model
runs**, with byte-identical final states within each input size and closed
model traffic ledgers. Increasing only the trailing isolated-source population
adds **980.74--993.04 ns per row** to the old adapter's measured event lifetime.
The unchanged v2 simulator adds **520.00 ns per row**. The optimized FPGA
adapter has no comparable positive scaling with these trailing rows.

This confirms that the optimized implementation removes the observed
trailing-row scaling for this control. It also preserves a reproducible timing
mismatch: the old-path incremental model cost is about 47% below the board.
**No timing parameter was fitted, and neither hardware timing nor original-A4
performance is admitted.** This is a diagnostic, not a graph-performance row.

## Fixed Problem

| Property | Frozen condition |
| --- | --- |
| Algorithm and clock | Weighted SSSP, 150 MHz, the same old/new U55C bitstreams as the paired board study |
| Graph sizes | 4,096; 8,192; 16,384; 32,768 vertices, all in one destination partition |
| Initial edges | `0->1->2->3->4`, each edge weight 8 |
| Batch | Insert `0->4` with weight 1 |
| Resident initial distances | Prefix `[0, 8, 16, 24, 32]`; remaining vertices unreachable |
| Published final distances | Prefix `[0, 8, 16, 24, 1]`; remaining vertices unreachable |
| Computation | Same active source `{0}` and two propagation rounds |
| PMA | Same occupied rows, slots, live payload and update; last occupied source is 3 |
| Repetition | Three paired board repetitions, alternating old/new order; one deterministic model run per arm/size |

An independent fixture audit checks the live mapping, old/new state, PMA slot
bytes and prefix row bounds. Their combined hash is identical across all four
sizes. Added vertices are isolated, not a different graph problem. The
destination partition and padded apply extent do not change. Larger allocations
can still change FPGA BO placement and vertex-state work, so this is not an
exclusive measurement of HBM read latency.

## Raw Results

Adapter event duration, in milliseconds. Each board entry is the median of
six event samples: two rounds in each of three independent executions. The
model entries are the median of its two rounds. This pooling describes event
lifetimes, not six independent graph workloads or a confidence interval.

| Vertices | Old FPGA | Old model | Optimized FPGA | Optimized model |
| ---: | ---: | ---: | ---: | ---: |
| 4,096 | 4.197154 | 2.132373 | 0.090283 | 0.003163 |
| 8,192 | 8.214282 | 4.262293 | 0.089383 | 0.003163 |
| 16,384 | 16.349262 | 8.522133 | 0.084478 | 0.003163 |
| 32,768 | 32.549211 | 17.041813 | 0.093793 | 0.003163 |

Incremental slopes are adjacent-size differences of these medians divided by
the number of added rows. They are descriptive differences, not fitted model
coefficients. Negative slopes are retained rather than clamped away.

| Size interval | Old FPGA ns/row | Old model ns/row | Optimized FPGA ns/row | Optimized model ns/row |
| --- | ---: | ---: | ---: | ---: |
| 4K to 8K | 980.744 | 520.000 | -0.220 | 0.000 |
| 8K to 16K | 993.040 | 520.000 | -0.599 | 0.000 |
| 16K to 32K | 988.766 | 520.000 | 0.569 | 0.000 |

The independent adapter-after-Little tail slopes are 984.541, 991.600 and
988.184 ns/row on the old FPGA, versus 520.000 in the model. All optimized
tail samples are zero. Here "Little" is the complete `lksg` kernel, including
Scatter; its end event is not an exclusive edge-read completion timestamp.
The tail is `max(adapter_end - Little_end, 0)`, not a sum of overlapping stages.

## What Remains Unexplained

- The effective serial directory path is slower on the FPGA than in the fixed
  model. The data do not isolate memory-controller latency, interconnect,
  protocol/clock conversion, or HLS waiting into separate causes.
- The optimized adapter still reports an 84--94 us median event lifetime, versus
  about 3.16 us in the model. Event lifetime can include downstream availability
  and dispatch-dependent waits. Calling the full difference "HBM latency" or
  "host overhead" would overstate the available counters.
- Both candidate flags are enabled: row prefetch and stop-after-last. This
  old/new control does not separately quantify the two optimizations.
- Model offsets are deterministic, not captured board BO addresses. Whole-path
  event spans also contain dispatch/relaunch gaps absent from the model.
- A four-row live prefix is a mechanism test, not evidence that original A4 and
  modified K4 have equal throughput on a real graph. SSSP is not original
  ReGraph's one-iteration PageRank comparison.

The next timing investigation must distinguish kernel-internal progress from
launch/consumer availability and characterize the actual AXI/platform path.
Changing `71` to a fitted delay from this sweep would not establish either
cause. A subsequent calibrated model must use explicit training boundaries and
new independent checks; this no-fit campaign stays immutable.

## Evidence And Reproduction

- [Complete results and individual samples](empty_rows.json)
- [Raw archive](raw_empty_rows.tar.gz) and [every-file SHA-256 index](empty_rows_raw_index.json)
- [Fixed v2 source/plugin evidence](../independent_channels/README.md)
- [Bitstream admission and prior real-graph board results](../../../adapter_optimization/BOARD_RESULTS.md)

The archive contains all four inputs, resident fixtures, 24 board outputs/logs,
eight model outputs/DRAM logs, commands/resource records, numerical source
snapshots, the host and exporter. Its index pins the parent source/plugin,
exporter and bitstream evidence packages. Large xclbins and the already archived
plugin are referenced by hashes rather than duplicated here. XRT/SST/DRAMSim3
and the recorded local binaries are required to rerun; portable tests do not
require those tools or original absolute data paths.

From the simulator repository root, with the frozen local dependencies:

```bash
taskset -c 120,121 python3 scripts/run_sharded_k4_empty_rows.py \
  --integration /home/chuxiao/grasu-regraph-integration \
  --host /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/trace_host/sharded_k4_sssp_native_host \
  --admission /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/route_combined_sssp_admission/summary.json \
  --exporter /data/chuxiao/experiments/sharded_k4_sst_sync_20261011/export_hls_fixture \
  --plugin-dir /data/chuxiao/experiments/sharded_k4_axi_channels_accounted_20261011/plugin_final \
  --channel-evidence docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst/independent_channels/channels.json \
  --output results/sharded_k4_stages/empty_rows_unique_run --device 0
python3 -m unittest discover -s tests -p 'test_sharded_k4_empty_rows*.py'
```

The runner refuses existing output, permits only the predeclared four sizes,
uses an exclusive idle-board check, runs one board job at a time, caps each child
at 8 GiB with a 16-GiB reserve, and retains raw failures. The measured largest
child peak RSS was 236.5 MiB for board execution and 40.2 MiB for SST. These are
`wait4` maximum-process RSS values, not simultaneous process-tree sums. Board
child wall time totaled 262.6 s; SST totaled 8.14 s, excluding packaging.

Ownership is split between `row_sweep.py` (execution), `row_sweep_analysis.py`
(invariants/statistics), and `row_sweep_delivery.py` (validation/packaging).
Seven focused tests verify the contract, fixture invariants, preserved negative
slopes, every archive member, all complete output bytes, source/plugin identity,
and recomputation of the published statistics. No numerical model, HLS, paper
or figure is changed by this checkpoint.
