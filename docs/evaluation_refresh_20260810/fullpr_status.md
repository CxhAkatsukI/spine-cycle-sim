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
[19:50:43] Run vpl: Step impl: Started
[20:12:15] Finished 2nd of 6 tasks (FPGA linking synthesized kernels to platform). Elapsed time: 01h 40m 43s

[20:12:15] Starting logic optimization..
[20:12:15] Phase 1 Initialization
[20:12:15] Phase 1.1 Core Generation And Design Setup
[20:13:17] Phase 1.2 Setup Constraints And Sort Netlist
[20:13:17] Phase 2 Timer Update And Timing Data Collection
[20:13:17] Phase 2.1 Timer Update
[20:13:17] Phase 2.2 Timing Data Collection
[20:13:17] Phase 3 Retarget
[20:13:48] Phase 4 Constant propagation
[20:14:18] Phase 5 Sweep
[20:15:20] Phase 6 BUFG optimization
[20:15:51] Phase 7 Shift Register Optimization
[20:15:51] Phase 8 Post Processing Netlist
[20:15:51] Phase 9 Finalization
[20:15:51] Phase 9.1 Finalizing Design Cores and Updating Shapes
[20:16:22] Phase 9.2 Verifying Netlist Connectivity
[20:16:53] Finished 3rd of 6 tasks (FPGA logic optimization). Elapsed time: 00h 04m 37s

[20:16:53] Starting logic placement..
[20:17:24] Phase 1 Placer Initialization
[20:17:24] Phase 1.1 Placer Initialization Netlist Sorting
```
