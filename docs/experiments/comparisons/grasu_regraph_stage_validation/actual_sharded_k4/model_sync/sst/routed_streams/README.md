# Routed Stream Capacities

## Finding

Both measured routed block designs use **32-beat FIFOs on the nine edge-path
connections**, whereas the earlier v1/v2 model used 16. Explicit v3 corrects
those capacities only. All six AU/SU/WK old/new runs retain complete FPGA
output equality, convergence and finite-traffic conservation. Their total
cycle changes are at most **0.101%**. This correction is required by the
hardware structure but does not explain the large nominal timing mismatch.

No clock, memory-delay, outstanding-request, physical-master, HBM-channel,
algorithm or input parameter is fitted or changed. The default simulator and
v1/v2 profile selections retain their previous values. Hardware timing and
the original-A4 comparison remain unadmitted.

## Structural Evidence

`stream_contract.py` validates every connection against both frozen routed
`.bd` JSON files, including producer/consumer wiring, FIFO type and depth.
The two identities are pinned in the v3 architecture profile.

| Connection | Count | v1/v2 | Routed / v3 |
| --- | ---: | ---: | ---: |
| Adapter to Little | 4 | 16 | 32 |
| Little to frontend mux | 4 | 16 | 32 |
| Frontend mux to merger | 1 | 16 | 32 |
| Source requests and responses | 8 | 16 | 16 |
| Merger to Apply, Apply to HBM wrapper | 2 | 16 | 16 |

The audit covers 19 inter-kernel streams. It establishes capacity and wiring,
not the exact generated FIFO latency or internal HLS pipeline schedule.
Internal model FIFOs remain depth 8. The v2 independent read/write correction
remains enabled in v3; no additional physical AXI initiators are introduced.

## Complete Timing Diagnostic

These use the predeclared first FPGA repetition, not a selected favorable
repeat. Model time is resident compute at 150 MHz; board span still includes
dispatch/relaunch gaps. The two windows are not identical.

| Graph | Adapter | v2 cycles | v3 cycles | v3 compute ms | FPGA span ms |
| --- | --- | ---: | ---: | ---: | ---: |
| AU | Optimized | 15,481,739 | 15,479,318 | 103.195 | 200.395 |
| SU | Optimized | 25,381,331 | 25,355,911 | 169.039 | 395.824 |
| WK | Optimized | 8,745,375 | 8,745,414 | 58.303 | 92.622 |
| AU | Original | 170,695,735 | 170,695,763 | 1,137.972 | 2,053.708 |
| SU | Original | 280,053,122 | 280,052,674 | 1,867.018 | 3,382.743 |
| WK | Original | 451,314,549 | 451,314,109 | 3,008.761 | 5,670.419 |

The nominal model/board ratios remain 0.427--0.629. Larger FIFOs can alter
arbitration and backpressure; they need not strictly reduce elapsed cycles.
The tiny WK increase is retained. All non-timing counters and per-round active
counts are required to remain equal across v2/v3.

## Verification And Delivery

The [report](streams.json) and [raw index](streams_raw_index.json) freeze the
model/build identities, source, complete inputs/outputs, DRAM logs, both routed
designs, board-comparator logs and verification records. The raw archive is
`raw_streams.tar.gz`. Parent FPGA outputs and earlier model evidence remain
in the hash-pinned [v1](../README.md) and [v2](../independent_channels/README.md)
packages rather than being silently replaced.

Verification passed 23/23 CTest executables, five exact legacy SST regressions,
six exact v2 replays with the same final plugin, six complete v3 runs, and
119 focused Python tests (including four independent portable-package checks).
The archived pre-packaging Python run passed 115 tests; the four package checks
ran after sealing the archive. Exact replay means **every result JSON field and all
external result bytes**, with no ignored fields. The portable package tests
rehash every archive member and recompute both the numerical comparisons and
the 19-stream structural audits without the original absolute data paths.

The first Python gate attempt failed before a watchdog's child could launch:
an outer 8-GiB hard address-space limit conflicted with its deliberate 64-GiB
child limit. That failed attempt is retained. The rerun uses the existing
process-tree watchdog, an 8-GiB RSS budget, 16-GiB reserve and 300-second timeout;
the nested timeout/termination test is not skipped.

## Reproduction

Use a fresh Release build and SST plugin, never a frozen campaign directory.
Build commands and dependencies are the same as the v2 checkpoint. Run the
existing matrix entry point twice with different outputs:

```bash
python3 scripts/run_routed_k4_timing_matrix.py \
  --integration /absolute/grasu-regraph-integration \
  --plugin-dir /absolute/fresh/plugin --exporter /absolute/export_hls_fixture \
  --contract configs/experiments/sharded_k4_routed_sssp_timing_v3.json \
  --output /absolute/fresh/matrix_v3 --jobs 2
```

Repeat with `sharded_k4_routed_sssp_timing_v2.json` and `replay_v2`. Keep all
numerical source frozen across the legacy run and both matrices. The runner
caps each child at 8 GiB and 900 seconds, reserves 16 GiB and uses at most two
matrix workers. `package_stream_checkpoint(root, campaign, output)` refuses
missing/mismatched gates or an already frozen output package.

Ownership stays in the existing `sharded_k4_stages` package: `stream_contract`
owns structural validation; `stream_delivery` owns cross-version admission and
packaging. The C++ composition has three explicitly named finite-depth fields;
only the separately selected v3 SST profile changes them to 32. Paper and
figure handoffs are unchanged.
