# Full PageRank Evidence Status

The current compact Full PageRank panel uses three correctness-admitted routed
K4-shared FPGA workloads: Amazon-2008, Web-Google, and Flickr. The plotted
metric is setup-inclusive G+R/Delta.hls latency speedup over three repetitions,
not the older kernel-window ratio.

This evidence is intentionally labeled `compact_one_partition`. The current
destination-sharded K4 Full PageRank xclbin has not yet been routed. Its build
is a background task and does not block simulator calibration or the remaining
figure refresh. If the route and full-graph correctness matrix pass, panel (d)
will be replaced without changing the other panels' layout.
