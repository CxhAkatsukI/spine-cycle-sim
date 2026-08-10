# Full PageRank Evidence Status

The current compact Full PageRank panel uses three correctness-admitted routed
K4-shared FPGA workloads: Amazon-2008, Web-Google, and Flickr. The plotted
metric is setup-inclusive G+R/Delta.hls latency speedup over three repetitions,
not the older kernel-window ratio.

Sharded K4 Full PageRank route status: `RUNNING`.

- Route directory: `/data/tmp/chuxiao/grasu_regraph_sharded_k4_fullpr_hw_646c8a8_20260810_route`
- PID: `619749`; running: `True`
- XCLBIN present: `False`
- Link summary present: `True`

This evidence is intentionally labeled `compact_one_partition` until the
destination-sharded K4 Full PageRank xclbin routes successfully and its
correctness/performance matrix passes. If that happens, panel (d) can be
replaced without changing the other panels' layout.

## Latest Route Log Tail

```text
[20:56:35] Phase 2.5.2 Physical Synthesis In Placer
[21:02:47] Phase 3 Detail Placement
[21:03:18] Phase 3.1 Commit Multi Column Macros
[21:03:18] Phase 3.2 Commit Most Macros & LUTRAMs
[21:06:24] Phase 3.3 Small Shape DP
[21:06:24] Phase 3.3.1 Small Shape Clustering
[21:06:55] Phase 3.3.2 Slice Area Swap
[21:07:26] Phase 3.3.2.1 Slice Area Swap Initial
[21:10:32] Phase 3.4 Place Remaining
[21:11:03] Phase 3.5 Re-assign LUT pins
[21:12:05] Phase 3.6 Pipeline Register Optimization
[21:12:36] Phase 3.7 Fast Optimization
[21:14:40] Phase 4 Post Placement Optimization and Clean-Up
[21:14:40] Phase 4.1 Post Commit Optimization
[21:17:15] Phase 4.1.1 Post Placement Optimization
[21:17:46] Phase 4.1.1.1 BUFG Insertion
[21:17:46] Phase 1 Physical Synthesis Initialization
[21:20:21] Phase 4.1.1.2 BUFG Replication
[21:20:21] Phase 4.1.1.3 Post Placement Timing Optimization
[21:41:33] Phase 4.1.1.4 Replication
[21:43:06] Phase 4.2 Post Placement Cleanup
[21:43:06] Phase 4.3 Placer Reporting
[21:43:06] Phase 4.3.1 Print Estimated Congestion
[21:43:37] Phase 4.4 Final Placement Cleanup
```
