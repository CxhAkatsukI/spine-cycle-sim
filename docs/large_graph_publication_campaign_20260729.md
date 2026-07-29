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
