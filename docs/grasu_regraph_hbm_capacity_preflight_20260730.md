# GraSU + ReGraph HBM Capacity Preflight

## Purpose

The conversion-free GraSU + ReGraph full-graph profile uses 23 physical U55C
HBM pseudo-channels with 512 MiB per channel. A case that cannot fit mandatory
row-offset storage is not a slow execution; it is physically outside the
frozen architecture capacity and must be reported as a capacity exclusion.

## Conservative proof

For `V` vertices, 65,536 vertices per destination partition, and 4 KiB packed
alignment, the mandatory row-offset lower bound is:

```text
P = ceil(V / 65536)
row_lower_bound = P * align_up(8 * V, 4096)
hbm_budget = 23 * 512 MiB = 12,348,030,976 bytes
```

This omits PMA segments, binary-search heads, source state, destination state,
degree state, and updates. Therefore `row_lower_bound > hbm_budget` proves
rejection without making assumptions about edge distribution. A lower bound
that fits does not prove admission; the execution still performs the complete
topology-dependent footprint and address-map checks.

## Formal exclusions

| Dataset | Vertices | Row lower bound | Frozen HBM budget | Disposition |
|---|---:|---:|---:|---|
| soc-Bitcoin | 24,575,382 | 73,726,464,000 B | 12,348,030,976 B | capacity-excluded |
| UK-2002 | 18,520,486 | 41,930,584,064 B | 12,348,030,976 B | capacity-excluded |

The first post-R19 Bitcoin retry reached the complete topology-dependent check
and reported an actual interleaved arena of 76,509,261,824 bytes. This is
consistent with, and larger than, the static 73,726,464,000-byte lower bound.
UK-2002 was soft-stopped before launch after the same lower-bound proof, avoiding
an unnecessary multi-GiB bootstrap allocation.

The amended formal manifest is:

```text
/data/tmp/chuxiao/large_graph_campaign_v1/formal_v3_remaining7_k4_weighted_admission_v2/campaign_manifest.json
```

It retains seven logical contract cases, emits five physical jobs, and records
two machine-readable capacity exclusions with execution IDs, profile hashes,
row lower bounds, channel geometry, and `performance_eligible=false`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/generate_publication_experiment_campaign.py \
  --contract configs/contracts/large_graph_publication_campaign_fullgraph_v3.json \
  --materialization-root /data/tmp/chuxiao/large_graph_campaign_v1 \
  --output-root /data/tmp/chuxiao/large_graph_campaign_v1/formal_v3_remaining7_k4_weighted_admission_v2 \
  --manifest /data/tmp/chuxiao/large_graph_campaign_v1/formal_v3_remaining7_k4_weighted_admission_v2/campaign_manifest.json \
  --python /usr/bin/python3 --sst /data/feiyang/sst/bin/sst \
  --lib-dir /data/tmp/chuxiao/fullgraph-v8-repair-native-build-20260730 \
  --capability-catalog configs/contracts/grasu_regraph_full_graph_capabilities_v7.json \
  --tier main_e2e --algorithm weighted_sssp \
  --system grasu_regraph_k4_shared --scenario insert --batch-size 8 \
  --dataset hollywood_2009 --dataset ljournal_2008 --dataset soc_bitcoin \
  --dataset soc_livejournal1 --dataset soc_orkut --dataset soc_pokec \
  --dataset uk_2002 --max-cycles 10000000000000
```

Capacity-excluded rows never enter latency, throughput, traffic, or energy
aggregates. They remain part of the frozen workload coverage ledger.
