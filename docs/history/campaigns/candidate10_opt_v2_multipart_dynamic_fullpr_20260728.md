# Candidate10 opt-v2 multi-partition dynamic Full PageRank

## Purpose

This experiment closes the dynamic PageRank input path for the optimized Spine
profile and the resource-normalized GraSU+ReGraph K=1 baseline. The graph has
65,537 vertices, so both systems cross the 65,536-vertex destination-partition
boundary. The six-record batch contains four inserts and two deletes and leaves
six unique `(src,dst)` records.

The earlier fixture inserted new weights at two already occupied keys. That was
ambiguous because both HLS organizations index logical edges by `(src,dst)`.
The corrected fixture uses four genuinely new keys. Generic Spine validation
now rejects a run unless materialized snapshot, maintenance output, and reader
input edge counts are identical. Shared comparison invocation also passes a
non-empty PageRank update to Spine rather than timing its initial graph only.

## Result

| System | Cycles | HBM requests | Host wall | Correctness |
|---|---:|---:|---:|---|
| Spine Candidate10 opt-v2 | 6,330,094 | 788,573 | 10.92 s | both oracles pass |
| GraSU+ReGraph K=1 | 5,017,117 | 904,253 | 18.65 s | both oracles pass |

GraSU+ReGraph is 1.262x faster on this deliberately sparse partition-scan case.
Spine issues 12.79% fewer backend requests, but its full-vertex PageRank state
processing and sparse two-partition control cost dominate the saved traffic.
This is useful bottleneck evidence; it is not a claim about average real graphs.

For Spine, all four graph-state counts equal six:

```text
materialized_snapshot_edges == maintenance_persisted_edges
                            == reader_edges == compute_edges
```

All architecture and mathematical oracle mismatch counts are zero, and the
maintenance, reader, compute, locality, AXI, and DRAM request ledgers close.

## Reproduction

Build or reuse the exact-idle SST/DRAMSim3 backend described in
`docs/dramsim3_exact_idle_advance_20260727.md`, then export its two paths. The
tracked wrapper is intentionally passed as `--sst`; the library resolver records
the isolated `libmemHierarchy.so` and simulator plugin SHA-256.

```bash
cd /home/chuxiao/spine-cycle-sim-publication
export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-script-repro-v1/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-script-repro-v1-install
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst

python3 scripts/run_sst_spine_vertical.py \
  --out-dir /data/tmp/chuxiao/candidate10_opt_v2_multipart_fullpr_spine_fixed_20260728 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh --lib-dir build/sst \
  --profile configs/architectures/spine_candidate10_opt_v2_reader_working_set.json \
  --scenario full_pagerank --validation-mode generic \
  --workload tests/data/grasu_regraph_partitioned_normalized_initial.slice \
  --update-workload tests/data/grasu_regraph_partitioned_normalized_update.slice \
  --pagerank-iterations 3 --pagerank-damping 0.85 \
  --max-cycles 20000000 --no-build

python3 scripts/run_sst_grasu_regraph_hls_pagerank.py \
  --out-dir /data/tmp/chuxiao/candidate10_opt_v2_multipart_fullpr_grasu_fixed_20260728 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh --lib-dir build/sst \
  --profile configs/architectures/grasu_regraph_candidate10_k1_multipart_pagerank_v4.json \
  --capability-catalog configs/contracts/grasu_regraph_k1_multipart_capabilities_v4.json \
  --workload tests/data/grasu_regraph_partitioned_normalized_initial.slice \
  --update-workload tests/data/grasu_regraph_partitioned_normalized_update.slice \
  --max-cycles 20000000 --no-build
```

Machine-readable evidence is in
`docs/evidence/candidate10_opt_v2_multipart_dynamic_fullpr_20260728.json`.
