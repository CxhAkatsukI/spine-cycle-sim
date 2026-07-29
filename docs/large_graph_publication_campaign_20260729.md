# Publication-scale real-graph campaign contract

The frozen contract is
`configs/contracts/large_graph_publication_campaign_v1.json`. It records the
nine reviewed decisions before formal execution: full-dataset labeling, the
11 real datasets plus R19-32, four algorithm semantics, Full PageRank's 4M-edge
cap, auditable soft-stop behavior, the tiered update matrix, K1/K4-shared
GraSU+ReGraph baselines, strict correctness admission, and final reporting
boundaries.

The primary Spine point is the bounded opt-v2 reader working-set design. The
primary multi-partition competitor is conversion-free GraSU+ReGraph K4 with
shared downstream/HBM arbitration. K1 remains a reported implementation
baseline; ideal K4 is an upper bound and cannot enter headline aggregates.
All three use the capacity-checked packed-v5 address profiles described in
`docs/grasu_regraph_runtime_packed_addressing_20260729.md`. Runtime packing
matches host-managed partition-buffer allocation; it does not increase the
frozen compute or HBM resources.

Large generated workloads and raw simulation outputs belong under
`/data/tmp/chuxiao`. The repository tracks only contracts, source hashes,
generated-workload manifests, compact evidence, plotting inputs, and
reproduction commands.

Audit source presence and file sizes:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/audit_large_graph_campaign.py
```

Recompute every source SHA-256 when preparing the formal run:

```bash
python3 scripts/audit_large_graph_campaign.py --rehash \
  --output /data/tmp/chuxiao/large_graph_campaign_v1/source_audit.json
```

Materialize one real dataset with bounded Python memory and external GNU sort:

```bash
python3 scripts/materialize_publication_workload.py \
  --dataset sx_askubuntu \
  --out-dir \
    /data/tmp/chuxiao/large_graph_campaign_v1/workloads/sx_askubuntu \
  --sort-parallel 16 --sort-memory 8G \
  --progress-path \
    /data/tmp/chuxiao/large_graph_campaign_v1/workloads/sx_askubuntu.progress.json
```

The materializer preserves external vertex IDs, validates the frozen source
SHA, removes self-loops, sorts and deduplicates edges, applies the contract's
directed/reciprocal projection, and emits deterministic positive weights. It
also emits insert, delete, weight-change, and mixed batches at 1/8/64/512/4096
user mutations. Full PageRank's 64K/256K/1M/4M slices are exact nested samples
under a deterministic edge-hash rank; they are not prefixes of source-sorted
edges, and their delete/weight-change batches are selected from that exact
slice. Residual PageRank uses the frozen
`deltahls_sink_free_linf_warm` contract: each original zero-outdegree vertex
receives an explicit self-loop, and a delete batch takes at most one edge from
each source whose original degree is at least two. Every generated artifact is
represented by count, byte size, and SHA-256 in
`materialization_manifest.json`.

Generate and monitor all 11 real-dataset materialization jobs:

```bash
python3 scripts/generate_publication_materialization_campaign.py \
  --output-root /data/tmp/chuxiao/large_graph_campaign_v1 \
  --manifest \
    /data/tmp/chuxiao/large_graph_campaign_v1/materialization_campaign.json
python3 scripts/run_large_graph_campaign.py \
  --manifest \
    /data/tmp/chuxiao/large_graph_campaign_v1/materialization_campaign.json \
  --run-dir \
    /data/tmp/chuxiao/large_graph_campaign_v1/materialization_run \
  --jobs 6 --large-jobs 4 --memory-reserve-gib 32
```

Run one correctness-gated formal non-CC execution:

```bash
python3 scripts/run_publication_case.py \
  --materialization-manifest \
    /data/tmp/chuxiao/large_graph_campaign_v1/workloads/sx_askubuntu/materialization_manifest.json \
  --system spine --algorithm weighted_sssp \
  --scenario insert --batch-size 8 \
  --out-dir /data/tmp/chuxiao/large_graph_campaign_v1/smoke/ask_spine_sssp
```

The formal runner rechecks graph, update, profile, and simulator-plugin hashes;
requires the child and parent correctness/memory gates; and stores a compact
full-result-vector digest next to the raw evidence.

The un-deduplicated contract contains 777 system runs. The campaign generator
must remove overlap between tiers before launch and reuse one execution's E2E,
update, memory, activity, and correctness outputs wherever their measurement
boundaries are identical.

## Long-run process protocol

The formal manifest is executed by a resource-aware process scheduler. It
reserves 32 GiB of host memory, limits simultaneous large jobs separately,
pins jobs to distinct physical cores by default, records process-group RSS and
CPU time, and resumes only jobs that previously passed under the identical
manifest hash. There is deliberately no automatic wall-clock timeout.

Each child may atomically update the JSON file named by
`SPINE_CAMPAIGN_PROGRESS_PATH`. Recognized fields include `phase`, `completed`,
`total`, `iteration`, and `eta_seconds`. Unknown-total iterative algorithms
report their current phase, iteration, throughput, and elapsed time instead of
inventing a completion percentage. Twenty minutes without a changed progress
record raises a visible warning but requires a human soft-stop decision.

Launch a generated manifest:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/run_large_graph_campaign.py \
  --manifest /data/tmp/chuxiao/large_graph_campaign_v1/campaign_manifest.json \
  --run-dir /data/tmp/chuxiao/large_graph_campaign_v1/run \
  --jobs 8 --large-jobs 4 --memory-reserve-gib 32
```

Watch one stable terminal snapshot every two seconds:

```bash
watch -n 2 python3 scripts/monitor_large_graph_campaign.py \
  --run-dir /data/tmp/chuxiao/large_graph_campaign_v1/run
```

Soft-stop a stalled job without losing its elapsed/progress evidence:

```bash
python3 scripts/control_large_graph_campaign.py \
  --run-dir /data/tmp/chuxiao/large_graph_campaign_v1/run \
  stop JOB_ID --reason 'no progress for 20 minutes; reviewed manually'
```

Resume all non-passing jobs with the same launch command plus `--resume`.
