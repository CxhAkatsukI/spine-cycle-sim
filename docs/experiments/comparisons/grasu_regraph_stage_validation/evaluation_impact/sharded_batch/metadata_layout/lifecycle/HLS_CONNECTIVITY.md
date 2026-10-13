# Metadata Copy Feasibility Boundary

## Read-Only Finding

The current SSSP routed connectivity permits all four search CUs' `binary_0`
and `row_offset_0` ports to address `HBM[0:22]`. The simulator's proposed
copy channels `[3, 9, 15, 20]` lie within those ranges. Metadata replication
therefore does not inherently require new search AXI ports or new bank IDs.
This is a connectivity check, **not** evidence that the complete candidate
is implemented, resource-feasible, routed or measured on FPGA.

The checked external repository was clean at commit
`6f5ebf2b0679f04f4f6e035e850fce7b6043a660`. No file in that repository was changed.
Files and SHA-256 identities:

| File in `grasu-regraph-integration` | SHA-256 |
| --- | --- |
| `tools/sharded_k4_native_host.cpp` | `19eba0e30b1d0527b668fd2fe59d88392c1dcc4afc70255400fceedd5ab05b4d` |
| `tools/sharded_k4_pagerank_native_host.cpp` | `459b8206f89a23d864fde2e19388f855d8ffdc13d8abbd0d74fe2cbe96348a4c` |
| `docs/evidence/sharded_k4_fullgraph_20260806/sssp/connectivity.tsv` | `33e99fa41a0c43538de35ee89eb44eccaf0080bbed235a40556d1c5e8727b4f9` |

## What The Current Host Actually Does

In the SSSP host, `DeviceShard` has one `row_dev` and one `binary_dev`
buffer (lines 40--41). Allocation and initial upload are at lines 590--611.
All four search kernels receive those same buffers (lines 753--758).
The adapter uses the original row buffer (line 917). Thus permission to
select different banks is not evidence of current per-CU copies.

The host's update-repeat loop restores PMA for diagnostic reruns; it does
not implement arbitrary consecutive dynamic batches or reservation growth.
The lifecycle experiment does not reinterpret that diagnostic loop as a
production multi-batch hardware implementation.

## Required Implementation Checks

1. Allocate and upload four full read-only copies of each table per shard,
   retaining the original row table for adapter reads. Validate every bank's
   capacity, address span and actual XRT allocation. The test's common bases
   are an explicit simulator choice, not measured device addresses.
2. Bind each search CU to its assigned copy. Retain the legal PMA/update
   lane ranges and do not add outstanding credits or simultaneous masters
   under the name of a placement-only change.
3. Reuse copies only while row bounds and binary heads remain immutable.
   Any re-reservation or growth must rebuild and upload **all** copies before
   search or adapter consumption. Include that work in the applicable host
   window; an extra byte count is not a wall-time measurement.
4. Verify the finite search and complete-cache candidate in the integrated
   HLS design, including schedule, clock and whole-G resource fit. The current
   routed direct-search/direct-HBM implementation is not that candidate.
5. Rerun payload, timing and host-inclusive checks on the rebuilt hardware.
   Existing old-bitstream Figure 7 measurements do not become candidate
   measurements merely because its connections would allow these buffers.

The narrow conclusion is that copy-bank connectivity is plausible within
the current port budget. Host lifecycle support, finite-search/cache HLS
and board performance remain separate, open acceptance gates.
