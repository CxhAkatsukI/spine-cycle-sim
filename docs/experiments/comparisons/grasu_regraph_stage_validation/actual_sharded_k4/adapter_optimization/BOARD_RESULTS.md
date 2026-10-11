# Routed SSSP Adapter Results

The combined adapter candidate improves the actual routed G+R path on all
three tested graphs. All 18 FPGA executions pass the independent oracle,
and each graph's old/new runs produce byte-identical result arrays and the
same convergence count. This establishes a real, repairable performance
problem in the old input path. It does not yet establish original-A4 parity.

## Measured Comparison

Times are medians of three repetitions per bitstream. Each pair uses the
same host executable, source vertex, input graph and eight logical updates.
Both begin with the old graph converged and resident, and finish after the
updated graph converges. Old/new execution order alternates across repeats.
Both bitstreams use four frontends, the same shared downstream and HBM
connections, and a 150-MHz data clock. Only the adapter XO was replaced.

| Graph | Vertices | Final edges | Shards | Rounds | Old setup-inclusive ms | New setup-inclusive ms | Old/new |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AU | 515,281 | 390,855 | 8 | 2 | 2,062.775 | 210.050 | 9.82x |
| SU | 567,316 | 616,126 | 9 | 2 | 3,396.578 | 409.201 | 8.30x |
| WK | 1,140,149 | 1,142,360 | 18 | 1 | 5,677.948 | 107.875 | 52.63x |

| Graph | Old compute event span ms | New compute event span ms | Old adapter-after-gather union ms | New union ms |
| --- | ---: | ---: | ---: | ---: |
| AU | 2,053.400 | 201.021 | 1,735.698 | 0.000 |
| SU | 3,382.743 | 395.824 | 2,726.459 | 0.000 |
| WK | 5,665.809 | 95.122 | 5,557.569 | 0.000 |

The event span includes overlapping kernel execution and intervening gaps.
The last two columns measure the union of intervals in which an adapter
remains running after its corresponding gather has completed. They are not
exclusive AXI-stall counters. Zero means no such interval was observed; it
does not mean all adapter, padding or directory work has disappeared.

## Interpretation

Stopping after the known final packet avoids traversing trailing empty
source rows. The candidate also reads eight contiguous row entries into a
small cache. The combined change eliminates the observed trailing-adapter
interval on these cases and materially reduces full dynamic latency.
The tests do not isolate the individual contribution of the two flags;
only their combined XO has been routed and timed on the board.

The improvement varies with graph layout, shard occupancy and convergence
rounds. In particular, WK's old compute span was dominated by the measured
trailing-adapter interval. These findings support optimizing the actual
sharded K4 implementation. They do not assign the earlier independent
PMA+A4 model's 74--791x prediction to the real FPGA.

The old G+R timings remain reproducible measurements of the old bitstream.
They must not stand in for the optimized baseline in a new Spine comparison.
Spine was not rerun by this checkpoint. No revised Spine/G+R ratio is claimed.
SO, PK, LJ, LJ08 and R19, optimized CC/PR, the synchronized production
simulator and the matched original-A4 comparison are still pending.

## Evidence And Reproduction

[board.json](board.json) gives exact medians, graph geometry, checks and
clock/topology/timing admission. [board_raw_index.json](board_raw_index.json)
authenticates every file in [raw_board.tar.gz](raw_board.tar.gz): all 18 raw
logs and result arrays, commands/resources, routed timing, extracted XRT
metadata, source snapshots and the recovered link record. Large XO/xclbin
binaries remain hash-indexed at their original local paths.

The candidate source is integration commit `429185d`. The earlier source,
RTL and HLS evidence remains in the separate pre-route package. The route
supervisor was lost before completion; the recovered record explicitly
retains that monitoring gap and the vendor's 4h22m55s duration. Admission
verified the completed artifact and timing independently before programming.

Run from the simulator worktree with a fresh board output directory:

```bash
taskset -c 120,121 python3 scripts/compare_sharded_k4_bitstreams.py \
  --integration /home/chuxiao/grasu-regraph-integration \
  --matrix /home/chuxiao/grasu-regraph-integration/docs/evidence/sharded_k4_fullgraph_20260806/sssp_fullgraph_u55c/matrix.tsv \
  --case au_weighted_sssp_resident \
  --host /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/trace_host/sharded_k4_sssp_native_host \
  --admission /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/route_combined_sssp_admission/summary.json \
  --output /data/chuxiao/experiments/fresh_paired_au --repeats 3 --device 0

python3 -m unittest discover -s tests -p test_sharded_k4_board_delivery.py
```

AU and SU used board 0 and CPU affinity 120--121; WK used board 1 and affinity
122--123. Each old/new pair stays on the same board. SU and WK ran concurrently,
with separate board leases and per-process 8-GiB caps plus a 16-GiB admission
reserve. Raw resource files state their actual RSS measurement scope.
