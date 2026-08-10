# Full PageRank Evidence Status

The current compact Full PageRank panel uses three correctness-admitted routed
K4-shared FPGA workloads: Amazon-2008, Web-Google, and Flickr. The plotted
metric is setup-inclusive G+R/Delta.hls latency speedup over three repetitions,
not the older kernel-window ratio.

Sharded K4 Full PageRank route status: `PASS_TIMING_MISS`.

- Route directory: `/data/tmp/chuxiao/grasu_regraph_sharded_k4_fullpr_hw_646c8a8_20260810_route`
- PID: `619749`; running: `False`
- XCLBIN present: `True`
- Link summary present: `True`

- Timing report present: `True`
- Timing summary: `WNS=-0.069 ns, TNS=-2.591 ns, setup failing endpoints=84; constraints_met=False`

This evidence is intentionally labeled `compact_one_partition` until the
destination-sharded K4 Full PageRank xclbin routes successfully and its
correctness/performance matrix passes. If that happens, panel (d) can be
replaced without changing the other panels' layout.

## Latest Route Log Tail

```text
INFO: [v++ 60-2331] SLR2 was specfied for compute unit pma_to_regraph_adapter_3, and verified as such in implementation.
INFO: [v++ 60-2331] SLR0 was specfied for compute unit pma_to_regraph_adapter_4, and verified as such in implementation.
INFO: [v++ 60-2331] SLR2 was specfied for compute unit pr_source_1, and verified as such in implementation.
INFO: [v++ 60-2331] SLR0 was specfied for compute unit process_cache_1, and verified as such in implementation.
INFO: [v++ 60-2331] SLR2 was specfied for compute unit process_cache_2, and verified as such in implementation.
INFO: [v++ 60-2331] SLR1 was specfied for compute unit process_ddr_1, and verified as such in implementation.
INFO: [v++ 60-2331] SLR2 was specfied for compute unit process_ddr_2, and verified as such in implementation.
INFO: [v++ 60-2331] SLR1 was specfied for compute unit regraph_frontend_mux_1, and verified as such in implementation.
INFO: [v++ 60-2331] SLR1 was specfied for compute unit regraph_pagerank_apply_1, and verified as such in implementation.
Check POST-VPL, containing 1 checks, has run: 0 errors
INFO: [v++ 60-244] Generating system estimate report...
INFO: [v++ 60-1092] Generated system estimate report: /data/tmp/chuxiao/grasu_regraph_sharded_k4_fullpr_hw_646c8a8_20260810_route/reports/link/link/system_estimate_grasu_regraph_full_pagerank.hw.xtxt
INFO: [v++ 60-586] Created /data/tmp/chuxiao/grasu_regraph_sharded_k4_fullpr_hw_646c8a8_20260810_route/build/grasu_regraph_full_pagerank.hw.ltx
INFO: [v++ 60-586] Created /data/tmp/chuxiao/grasu_regraph_sharded_k4_fullpr_hw_646c8a8_20260810_route/build/grasu_regraph_full_pagerank.hw.xclbin
INFO: [v++ 60-1307] Run completed. Additional information can be found in:
	Guidance: /data/tmp/chuxiao/grasu_regraph_sharded_k4_fullpr_hw_646c8a8_20260810_route/reports/link/link/link_guidance.html
	Timing Report: /data/tmp/chuxiao/grasu_regraph_sharded_k4_fullpr_hw_646c8a8_20260810_route/reports/link/link/imp/impl_1_hw_bb_locked_timing_summary_routed.rpt
	Vivado Log: /data/tmp/chuxiao/grasu_regraph_sharded_k4_fullpr_hw_646c8a8_20260810_route/logs/link/link/vivado.log
	Steps Log File: /data/tmp/chuxiao/grasu_regraph_sharded_k4_fullpr_hw_646c8a8_20260810_route/logs/link/link/link.steps.log

INFO: [v++ 60-2343] Use the Vitis Unified IDE to visualize and navigate the reports. Run the following command.
    vitis -a/ --analyze /data/tmp/chuxiao/grasu_regraph_sharded_k4_fullpr_hw_646c8a8_20260810_route/build/grasu_regraph_full_pagerank.hw.xclbin.link_summary
INFO: [v++ 60-791] Total elapsed time: 5h 13m 5s
INFO: [v++ 60-1653] Closing dispatch client.
```
