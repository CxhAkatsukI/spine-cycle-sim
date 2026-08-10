# GraSU + ReGraph full-graph simulator support (v7)

Date: 2026-07-29

## Scope and claim boundary

This change removes the simulator's false requirement that every packed
GraSU/ReGraph buffer fit inside one 512 MiB HBM pseudo-channel. It does not
claim that the new integrated address mapper has been synthesized in HLS.

- Preserved: the execution-driven GraSU update, PMA, ReGraph Map/Reduce,
  finite FIFO, AXI, outstanding-request, arbitration, response queue, and
  DRAMSim3 models.
- Added: a capacity-checked logical-to-physical HBM address mapper.
- HLS evidence: the existing routed compute/update kernels remain the
  implementation foundation.
- Pending HLS evidence: the 23-PC mapper and shared metadata read crossbar.

The v5/v6 profiles are unchanged. The new behavior is enabled only by the
eight `*_fullgraph_v7.json` profiles and
`configs/contracts/grasu_regraph_full_graph_capabilities_v7.json`.

## Why v5/v6 rejected large graphs

`runtime_packed_v1` placed every partition's row bounds, binary heads, and PMA
arrays in one logical address window. The SST backend then required the whole
window to fit one 512 MiB pseudo-channel. Full PageRank preserves the external
vertex-ID range, so a graph with millions of vertices has a large dense row
table for every destination partition. This caused a capacity exception before
simulation, even though the frozen comparison platform budgets 23 HBM
pseudo-channels.

This was a simulator address-map limitation, not host OOM and not an algorithm
correctness failure.

## v7 physical map

The frontend still emits the same logical AXI requests. Immediately before HBM
arbitration, the backend maps each request as follows:

1. Every unique logical buffer receives a non-overlapping range in a global
   arena.
2. Read-only row bounds and binary-search heads use one coherent physical copy;
   their four logical GraSU ports alias that copy and contend at the mapper.
3. Update arrays, four PMA arrays, primary/mirror source state, vertex state,
   and degree state receive independent arena allocations.
4. Each 64-byte global line is striped over physical pseudo-channels 0 through
   22.
5. Arbitration, per-channel outstanding limits, DRAM requests, and memory
   locality statistics use the mapped physical channel and address.
6. Functional payload storage keeps the original logical address, so timing
   translation cannot change the graph algorithm state.

The run fails before SST launch if the unique arena exceeds
`23 * 512 MiB`. The C++ backend also fails if a request is outside the mapping,
crosses a stripe line, targets an unbound channel, or exceeds local capacity.

The ledger includes 64-byte tail padding and the complete ReGraph partition
span for vertex and degree arrays. These details were found by fail-closed
smoke tests and are real AXI work, not exceptions added to pass the test.

## Capacity evidence

The previously rejected LiveJournal Full PageRank case has:

- vertices: 5,363,260
- selected edges: 4,000,000
- destination partitions: 82
- unique physical arena: 3,846,545,408 bytes
- frozen HBM capacity: 12,348,030,976 bytes (`23 * 512 MiB`)
- utilization: 31.15%
- largest per-PC mapped end: 167,241,152 bytes

It now passes address admission with no modulo aliasing.

## Correctness smoke evidence

All tests used the O3/LTO SST plugin produced from commit `f7d2117` and required
zero architecture-oracle and mathematical-oracle mismatches.

| Mode | K | Cycles | Iterations | Backend requests | Result |
|---|---:|---:|---:|---:|---|
| Weighted SSSP | 1 | 99,888 | - | 33,848 | PASS |
| Full PageRank | 1 | 1,917,923 | 3 | 370,639 | PASS |
| Full PageRank | 4 shared | 1,917,923 | 3 | 370,639 | PASS (one partition) |
| Thresholded residual PageRank | 1 | 5,540,954 | 82 | 7,432,205 | PASS |
| Connected Components | 1 | 133,840 | 3 | 50,816 | PASS |

Reproduce the Full PageRank smoke:

```bash
python3 scripts/run_sst_grasu_regraph_hls_pagerank.py \
  --profile configs/architectures/grasu_regraph_candidate10_k1_multipart_pagerank_fullgraph_v7.json \
  --capability-catalog configs/contracts/grasu_regraph_full_graph_capabilities_v7.json \
  --workload tests/data/hls_full_pagerank_large_real/real_amazon_2008_large_v19399_e50000.slice \
  --update-workload tests/data/hls_full_pagerank_large_real/real_amazon_2008_large_v19399_e50000_insert_u8.slice \
  --out-dir /data/tmp/chuxiao/grasu_fullgraph_v7_smoke \
  --sst /data/feiyang/sst/bin/sst \
  --lib-dir /data/tmp/chuxiao/grasu-fullgraph-v7-native-build-20260729 \
  --max-cycles 10000000000 \
  --no-build
```

## Formal repair campaign

The frozen formal contract is
`configs/contracts/large_graph_publication_campaign_fullgraph_v2.json`.
It pins profile hashes, the v7 capability catalog, and plugin SHA-256
`a8657ed6eef8c8f0136ccd7b42e1532a94bfcd813500d5ecc0b0c4e28601668f`.

The first repair campaign reruns the eight K1/K4-shared Full PageRank cases that
previously failed capacity admission:

```bash
python3 scripts/run_large_graph_campaign.py \
  --manifest /data/tmp/chuxiao/large_graph_campaign_v1/fullgraph_v2_repair/campaign_manifest.json \
  --run-dir /data/tmp/chuxiao/large_graph_campaign_v1/fullgraph_v2_repair/run \
  --jobs 2 \
  --large-jobs 2 \
  --memory-reserve-gib 64 \
  --memory-emergency-gib 64 \
  --memory-recovery-gib 80 \
  --max-starts-per-sample 1 \
  --resume
```

Monitor it with:

```bash
watch -n 2 python3 scripts/monitor_large_graph_campaign.py \
  --run-dir /data/tmp/chuxiao/large_graph_campaign_v1/fullgraph_v2_repair/run
```

## Host-memory circuit breaker

The campaign scheduler now reserves estimated RSS for processes that have
started but have not reached steady-state RSS. It starts at most the configured
number of new jobs per sample. If Linux `MemAvailable` drops below 64 GiB, it
sends SIGTERM to the largest running process groups until projected available
memory reaches 80 GiB; after 10 seconds it escalates remaining processes to
SIGKILL. Stopped jobs retain elapsed time, peak RSS, logs, and an auditable
reason, and are queued again by a later `--resume` run. Passed jobs are retained.

This protects host memory. It does not make two independent campaign schedulers
share their startup commitments, so each formal campaign should still use
conservative job limits.
