# Publication Component Activity Evidence

## Scope

Formal publication case results already carry execution-driven component
counters in `scalar_metrics`. The publication analyzer now normalizes those
counters into `component_activity_rows.csv`. Every row has the same identity as
its correctness-gated case result and retains the formal plugin SHA-256.

This output is **workload-specific activity, not total accelerator energy**.
It complements, but must not be conflated with:

- DRAMSim3 command and background HBM energy in `system_rows.csv`;
- Vivado vectorless hierarchy power in `component_power.csv`; and
- routed FPGA resource and timing evidence in `ppa_summary.csv`.

## Component contracts

| System | Components | Activity represented |
|---|---|---|
| Spine | maintenance | update cycles, edge visits, memory requests, scan/writer stalls |
| Spine | reader | active cycles, streamed edge work, memory requests, queue/window stalls |
| Spine | compute | active cycles, edge/apply work, memory requests, on-chip pipeline stalls |
| Spine | onchip_state_arrays | selected tiny-BRAM, vertex-state URAM, and bitmap accesses |
| Spine | axis_streams | edge/value transfers and stream backpressure |
| Spine | hbm_frontend | accepted requests, completed reads/writes, AXI/HBM stalls |
| GraSU+ReGraph | update_pma | update cycles, PMA/row/degree accesses, backend requests |
| GraSU+ReGraph | source_cache | source preparation/map cycles, reads, replicated lane writes, stalls |
| GraSU+ReGraph | gather | bank updates, merge/reset cycles, derived physical bank accesses, stalls |
| GraSU+ReGraph | merger | consumed rows, emitted bursts, output stalls |
| GraSU+ReGraph | apply | input work, state reads/writes, window and pipeline stalls |
| GraSU+ReGraph | compute_pipeline_aggregate | compute span, active work, requests, AXIS stalls |
| GraSU+ReGraph | hbm_frontend | accepted requests, completed reads/writes, AXI/HBM stalls |

Total and per-round aliases are mutually exclusive in each counter contract.
The analyzer selects one representation instead of adding both. Distinct stall
causes are additive. Missing architecture counters remain zero; they are not
inferred from edge count or elapsed time. The only computed cycle fallback is
an explicitly labeled aggregate compute span, `total - update - reader`, when a
runner does not export a direct compute-cycle counter.

## Invariants

For the 2026-07-30 live snapshot:

- 55 passing executions produce 361 activity rows;
- every Spine execution has exactly six component rows;
- every GraSU+ReGraph execution has exactly seven component rows;
- every row uses `workload_specific_activity_not_total_energy`;
- all counters are finite, integer, and nonnegative; and
- every HBM component closes `read_events + write_events == backend_requests`.

The snapshot grows as new formal executions pass. Failed or missing executions
cannot enter this file because the same publication-result validator and
correctness gate run before activity extraction.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
scripts/analyze_active_publication_campaigns.sh
python3 scripts/render_live_large_graph_report.py
python3 -m unittest tests.test_publication_analysis \
  tests.test_live_large_graph_report
```

Generated paths:

```text
/data/tmp/chuxiao/large_graph_campaign_v1/live_publication_analysis/component_activity_rows.csv
docs/paper/data/large_graph_campaign/component_activity.csv
```

The activity CSV supports later workload-calibrated module-energy work, but
that future conversion requires an explicit per-event characterization for
each covered memory and logic component. The current report does not multiply
these counters by vectorless power or present the result as energy.
