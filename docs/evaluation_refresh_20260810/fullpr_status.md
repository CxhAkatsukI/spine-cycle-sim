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
[22:48:15] Phase 14.1 Fix Topology Constraints
[22:48:15] Phase 14.2 Pre Route Cleanup
[22:48:46] Phase 14.3 Global Clock Net Routing
[22:52:23] Phase 15 Reset Design
[22:52:23] Phase 15.1 Create Timer
[22:53:25] Phase 16 Leaf Clock Prog Delay Opt
[22:54:58] Phase 16.1 Optimize Skews
[22:54:58] Phase 16.1.1 Leaf ClockOpt Init
[22:57:33] Phase 16.2 Post SkewOpt Delay Cleanup
[22:57:33] Phase 16.2.1 Delay CleanUp
[22:59:06] Phase 16.3 Post SkewOpt Hold Fix
[22:59:06] Phase 16.3.1 Hold Fix Iter
[23:02:44] Phase 17 Depositing Routes
[23:03:14] Phase 18 Resolve XTalk
[23:03:14] Phase 19 Post Process Routing
[23:03:45] Phase 20 Post Router Timing
[23:05:50] Phase 21 Physical Synthesis in Router
[23:05:50] Phase 21.1 Physical Synthesis Initialization
[23:09:27] Phase 21.2 Critical Path Optimization
[23:13:04] Phase 22 Route finalize
[23:13:04] Phase 23 Post-Route Event Processing
[23:14:37] Finished 5th of 6 tasks (FPGA routing). Elapsed time: 01h 19m 37s

[23:14:37] Starting bitstream generation..
```
