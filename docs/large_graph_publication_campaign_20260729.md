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
