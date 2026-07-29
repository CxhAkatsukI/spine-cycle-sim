# Publication-scale graph evaluation campaign

The frozen contract is
`configs/contracts/large_graph_publication_campaign_v1.json`. It records the
reviewed decisions before formal execution: full-dataset labeling, the 11 real
datasets plus a separately labeled R19-32 synthetic endpoint, four algorithm
semantics, Full PageRank's 4M-edge
cap, auditable soft-stop behavior, the tiered update matrix, K1/K4-shared
GraSU+ReGraph baselines, strict correctness admission, and final reporting
boundaries.

The primary Spine point is the bounded opt-v2 reader working-set design. The
primary multi-partition competitor is conversion-free GraSU+ReGraph K4 with
shared downstream/HBM arbitration. K1 remains a reported implementation
baseline; ideal K4 is an upper bound and cannot enter headline aggregates.
All three use capacity-checked runtime-packed address profiles described in
`docs/grasu_regraph_runtime_packed_addressing_20260729.md`. The K4-shared and
Connected Components additions are frozen in packed-v6 profiles documented in
`docs/grasu_regraph_publication_profiles_v6_20260729.md`. Runtime packing
matches host-managed partition-buffer allocation; it does not increase the
frozen compute or HBM resources.
The formal plugin is Candidate92 native+PGO at
`/data/tmp/chuxiao/candidate92-capacity-hot-ledger-native-pgo-build-20260729`; the
contract pins SHA-256
`88d44610461b876ec6617b705e338ed866f4ca18c41e1925bee4f8a26fcc3854`,
and every formal runner rejects a different binary. Candidate92 retains the
GraSU weighted destination-partition correction, selects only capacity-safe
Spine carry targets, and mirrors the current HLS host's measured-indegree
hot/cold resident classification.

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
    /data/tmp/chuxiao/large_graph_campaign_v1/materialization_campaign.json \
  --include-r19
python3 scripts/run_large_graph_campaign.py \
  --manifest \
    /data/tmp/chuxiao/large_graph_campaign_v1/materialization_campaign.json \
  --run-dir \
    /data/tmp/chuxiao/large_graph_campaign_v1/materialization_run \
  --jobs 6 --large-jobs 2 --memory-reserve-gib 64
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

The contract contains 777 logical views over the 11 real datasets plus 12
separately reported R19-32 endpoint views. The campaign generator removes
overlap between tiers before launch and reuses one execution's E2E, update,
memory, activity, and correctness outputs wherever their measurement boundaries
are identical. Candidate92 admits 747 logical views and reduces them to 623
physical executions. It excludes 42 Spine views before launch because the
preserved vertex-ID ranges of `soc_bitcoin` (13 views) and `uk_2002` (29 views)
exceed the frozen `MAX_N=2^24`; their GraSU+ReGraph views remain runnable.

Generate the full de-duplicated execution manifest:

```bash
python3 scripts/generate_publication_experiment_campaign.py \
  --materialization-root /data/tmp/chuxiao/large_graph_campaign_v1 \
  --output-root /data/tmp/chuxiao/large_graph_campaign_v1/formal_candidate92_v1 \
  --manifest \
    /data/tmp/chuxiao/large_graph_campaign_v1/formal_candidate92_v1/campaign_manifest.json
```

Use repeatable `--tier`, `--dataset`, `--algorithm`, and `--system` filters for
reviewed pilot or repair runs. For example, the 12-run AskUbuntu main-E2E pilot
is generated with `--tier main_e2e --dataset sx_askubuntu`. R19-32 can be
isolated with `--tier endpoint_scalability`.

## Long-run process protocol

The formal manifest is executed by a resource-aware process scheduler. It
reserves 64 GiB of host memory, starts at two simultaneous large jobs,
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
  --manifest \
    /data/tmp/chuxiao/large_graph_campaign_v1/formal_candidate92_v1/campaign_manifest.json \
  --run-dir \
    /data/tmp/chuxiao/large_graph_campaign_v1/formal_candidate92_v1/run \
  --jobs 6 --large-jobs 2 --memory-reserve-gib 64
```

Watch one stable terminal snapshot every two seconds:

```bash
watch -n 2 python3 scripts/monitor_large_graph_campaign.py \
  --run-dir \
    /data/tmp/chuxiao/large_graph_campaign_v1/formal_candidate92_v1/run
```

Soft-stop a stalled job without losing its elapsed/progress evidence:

```bash
python3 scripts/control_large_graph_campaign.py \
  --run-dir /data/tmp/chuxiao/large_graph_campaign_v1/run \
  stop JOB_ID --reason 'no progress for 20 minutes; reviewed manually'
```

Resume all non-passing jobs with the same launch command plus `--resume`.
