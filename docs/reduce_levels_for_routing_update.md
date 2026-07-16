# Simulator Update For `reduce-levels-for-routing`

## Spine Source Baseline

The simulator was updated after inspecting:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels
origin/reduce-levels-for-routing
cbd3ceb test: validate full-scale skewed RMAT storage
```

The user's local exploration branch was preserved separately:

```text
/home/chuxiao/spine-dynamic-graph
codex/explore-reduce-routing
f02d047 Record full Spine BFS hardware diagnostics
```

## Architecture Changes Reflected

The previous simulator modeled the older split evidence mostly as an L0/L1
capacity boundary. The current simulator now models:

```text
MAX_N = 16777216
VS_PARTITION_SIZE = 1048576
destination partition = dst / VS_PARTITION_SIZE
MAX_SORT_N = 131072
levels = 11
level ratio = 2
cold families = 16 destination partitions
hot families = 16 hashed hot shards
family total capacity = 16891904 edges
L10 family capacity = 8388608 edges
```

It also adds:

```text
measured in-degree hot/cold classification
per-family binary target selection
cold and hot carry counters
tiny-active/full-path SSSP counters
```

## Important Interpretation

There are now two different storage situations:

```text
incremental update path:
  batches flow through L0/L1/... binary carry
  a one-family 131072+1 update still fails at L1 capacity

graph preload / raw RMAT storage path:
  measured hot destinations are placed into hot shards
  latest HW evidence shows exact raw RMAT-24-9 stores and runs correctly
```

So the simulator should not use the old conclusion "large concentrated graph is
always unsupported" as a global statement. The better statement is:

```text
large concentrated incremental updates can still fail at low-level binary carry;
full raw skewed graph preload is handled by hot/cold classification in the new branch.
```

## Current Suite Evidence

The updated suite command is:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_spine_suite.py \
  --config configs/spine_current.yaml \
  --out-dir results/spine_v0_suite
```

Current summary:

```text
small_chain_v64                 PASS  cycles=549     sssp_iterations=64
small_star_v4096_u1024          PASS  cycles=264734  sssp_iterations=2
small_spread_v4096_u1024        PASS  cycles=263982  sssp_iterations=3
small_hotdst_v4096_u1024        PASS  cycles=263710  sssp_iterations=1
balanced_full_plus_one          PASS  cycles=402850  carry_count=1
one_partition_full_plus_one     FAIL  reason=level_family_capacity
large_chain_v4096               PASS  cycles=9180    sssp_iterations=4096
large_star_v1048576_u65536      FAIL  reason=level_family_capacity
large_spread_v262144_u65536     FAIL  reason=level_family_capacity
large_hotdst_v262144_u65536     FAIL  reason=level_family_capacity
random_rmat_small               PASS  cycles=266827
```
