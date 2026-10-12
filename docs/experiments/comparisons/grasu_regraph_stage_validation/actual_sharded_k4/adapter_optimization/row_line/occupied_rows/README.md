# Occupied-Row RTL Observation

## Finding

The actual whole-line adapter still processes occupied rows serially. In the
unchanged twelve-case production-RTL bench, adjacent one-segment rows usually
start 84 clocks apart at synthetic memory latency L=64. Increasing every row
from one to three segments adds only 68 clocks across 17 rows: within a row,
reads overlap; across rows, the helper is repeatedly started and completed.
This supports investigating a bounded pipeline across row boundaries in the
**production HLS**, not merely lowering simulator latency parameters.

This is a controlled RTL observation, **not a board measurement, calibrated
HBM result, exclusive stall breakdown, or proof of a real-graph slowdown**.
The [A4 control](../a4_control/README.md) remains a separate fixed-model result.
Neither its 24--26x gap nor the older independent PMA+A4 gap is measured here.

## Evidence

| Item | Location |
| --- | --- |
| All twelve cases, both immutable XOs, individual row timelines | [results.json](evidence/results.json) |
| Per-file identities and archive hash | [verification.json](evidence/verification.json) |
| Production XOs/RTL, unchanged bench, passive monitor, commands and raw logs | [raw_occupied_rows.tar.gz](evidence/raw_occupied_rows.tar.gz) |
| 332 Python regression checks, resource record and frozen test sources | [regressions.json](evidence/regressions.json), [raw_regressions.tar.gz](evidence/raw_regressions.tar.gz) |
| Experiment code | `spine_cycle_sim/experiments/sharded_k4_stages/row_line/occupied_rows/` |
| Read-only SystemVerilog observer | `cpp/tests/routed_regraph/occupied_row_monitor.sv` |
| Admission and mutation tests | `tests/test_sharded_k4_occupied_rows.py` |

The reference skip-empty XO and candidate whole-line XO are exactly those in
the [parent study](../README.md). No HLS, numerical simulator, AXI responder,
sink schedule or input packet changed. For **each arm**, all original case
records replay exactly: every request/response address and cycle, completion,
packet count and first/last accepted packet. The passive observer additionally
records every accepted packet and every occupied helper invocation.

## Selected Observations

All rows below use the whole-line candidate and synthetic L=64 unless noted.
Every case, including the reference and backpressure, remains in the report.

| Source layout | Segments per occupied row | RTL clocks | Helper lifetimes, sum | Median helper lifetime | Maximum outstanding reads |
| --- | --- | --- | --- | --- | --- |
| 17 occupied sources | 1 | 1735 | 1377 | 81 | 1 |
| 17 occupied sources | 3 | 1803 | 1445 | 85 | 3 |
| Only source 16 occupied | 1 | 439 | 81 | 81 | 1 |
| Only source 0 occupied | 1 | 239 | 81 | 81 | 1 |
| Sources 0, 7, 14 occupied | 1 | 519 | 243 | 81 | 1 |
| 17 occupied, sink stall=1000 | 1 | 2416 | 2058 | 81 | 1 |
| 17 occupied, L=128 | 1 | 3079 | 2465 | 145 | 1 |

For dense one-segment rows, start gaps are 84 clocks within a cached row
line and 160 at the two line transitions. Three-segment rows use 88 and
164 clocks respectively; their three PMA reads issue two clocks apart.
The occupied helper lifetime does not improve in the no-stall cases when
switching from skip-empty to whole-line reads. Directory changes reduce
the outside-helper portion, not the repeated occupied-row calls.

The synthesis report corroborates that the inner segment loop has achieved
II=2 and iteration latency 75, while its parent helper is not pipelined.
This report is in the parent raw package. It is a synthesis estimate, not a
routed clock or a memory-latency-independent per-row charge.

**Do not treat the lifetime sums as additive stage costs.** They include
memory and output waits. HLS helper `ap_done` can precede the last accepted
AXIS packet because the output interface buffers data. In the stalled case,
source 0 completes its helper before either packet is accepted; source 1
then waits longer. Thus the helper's completion is not adapter publication,
and an exclusive stall attribution would require additional observations.

The last-only versus first-only cases also show that empty-source traversal
and directory reads still matter. This probe does not justify removing
those costs or adding a free sparse index in the simulator.

## Reproduce And Review

From the simulator worktree root, use fresh output and delivery directories:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.occupied_rows.study \
  --reference /data/chuxiao/experiments/sharded_k4_skip_empty_segment_20261011/production-v2/adapter.hw.xo \
  --candidate /data/chuxiao/experiments/sharded_k4_row_line_20261011/attempt-v1/production/adapter.hw.xo \
  --output /data/chuxiao/experiments/fresh_occupied_rows \
  --vivado-bin /data/yxx/tools/xilinx/Vivado/2024.1/bin

python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.occupied_rows.delivery \
  --run /data/chuxiao/experiments/fresh_occupied_rows \
  --destination /data/chuxiao/experiments/fresh_occupied_rows_delivery

python3 -m unittest discover -s tests -p 'test_sharded_k4_occupied_rows.py'
```

`analysis.py` owns observation/conservation, `study.py` bounded execution,
`recheck.py` frozen raw admission and `delivery.py` archive verification.
Each compile/elaborate/simulate step is serial, bounded to 4 GiB tree RSS
and 120 seconds, with a live 16-GiB reserve. There is no separate aggregate
parent watchdog. The archive rechecks after fresh temporary extraction,
without relying on original local RTL, XO or source paths. Proprietary
tools and compiled simulation images are indexed, not redistributed.

The failed first observer attempt is preserved under `development/0_run-v1/`
in the archive and is not admitted. It mistook HLS's idle-high `ap_done`
after reset for an unsolicited helper completion. The corrected observer
only logs completion of an active invocation; the original complete replay
gate was retained. No production RTL or timing assumption was changed.

All 332 sharded-K4 Python tests pass; 15 structure tests, documentation layout,
catalogs and whitespace also pass. The test subprocess stayed within its
declared 3-GiB/240-second gate. A wrapper mistakenly applied the stricter
4-GiB/120-second RTL-specific checker afterwards and rejected that different
budget declaration, not the test results. The unmodified resource/log records
were independently checked against the correct declared gate and retained.

## Next Gate

Implement a default-off, finite-capacity cross-row pipeline in the owning
integration repository. Preserve packet order, dummy/filter behavior,
backpressure, empty rows, unaligned boundaries and the final `last` marker.
Check all edge formats and production RTL before synchronizing its distinct
simulator path. Preserve this version as the measured/probed reference.
Routing still requires the unchanged 40-GiB tree budget plus 16-GiB reserve;
there is no new FPGA timing or original-A4 performance claim yet.
