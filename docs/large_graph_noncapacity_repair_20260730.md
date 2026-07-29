# Large-graph non-capacity failure repair (2026-07-30)

## Scope

This repair addresses the six failures that remained after the full-graph HBM
address-capacity repair:

- two GraSU+ReGraph K4 shared Full PageRank validation failures; and
- four Spine weighted-SSSP delete/weight-change failures on SX-AskUbuntu.

The unrelated eight HBM address-capacity failures are handled by the running
`fullgraph_v2_repair` campaign and are not changed here.

## Root causes and fixes

### Sparse multipart PageRank source-cache validation

The K4 simulation completed successfully and produced a correct final rank
vector, but the Python validator estimated source-cache requests from each
partition's maximum source ID. That estimate assumes all source-buffer windows
up to the maximum are visited. The execution-driven reader instead prefetches
its initial windows and skips empty source ranges.

The validator now derives the expected request ledger from the actual live
source set in every destination partition by calling
`expected_partitioned_source_cache_requests`. Request, response-line, and lane
write counts remain exact conservation checks. `--reuse-result` allows a
completed `result.json` plus its DRAM statistics to be revalidated without
rerunning SST.

Recovered evidence:

| Dataset | System | Cycles | Source-cache requests | Backend requests | Result |
|---|---|---:|---:|---:|---|
| WikiTalk | GraSU+ReGraph K4 shared | 243,331,952 | 372 | 66,883,446 | PASS |
| Hollywood-2009 | GraSU+ReGraph K4 shared | 229,260,619 | 3,588 | 69,089,482 | PASS |

Both rows have zero architecture-oracle and mathematical-oracle mismatches.
Their child manifests set `sst_result_reused=true`; this means only validation
was repeated, not simulation.

### Spine non-monotonic weighted SSSP capacity

Delete and weight-increase updates use the paper's exact timed-full-rebuild
fallback. The old campaign fed the 390,847-edge SX-AskUbuntu graph back through
maintenance, while the frozen Spine hardware contract has
`MAX_SORT_EDGES=131072`. The generic `reset_batch` assertion hid this concrete
capacity violation.

The repaired experiment contract keeps insertion on the full directed graph.
Delete, weight change, and mixed weighted-SSSP cases use the same deterministic
64,000-edge real-topology hash slice for Spine, GraSU+ReGraph K1, and
GraSU+ReGraph K4 shared. The graph, update projection, source policy, and edge
cap are therefore pairwise identical. This is a bounded non-monotonic result,
not a full-graph result.

The C++ core now reports the actual edge count and `MAX_SORT_EDGES`. The Python
runner rejects an impossible full rebuild before SST startup. Contract
`large_graph_publication_campaign_fullgraph_v3.json` freezes the 64K cap and
the 131,072-edge hardware limit so the scope cannot change after results are
observed.

Direct AU smoke evidence:

| Scenario | Graph edges | Cycles | Backend requests | Result |
|---|---:|---:|---:|---|
| delete u8 | 64,000 | 37,369,521 | 6,359,315 | PASS |
| weight change u8 | 64,000 | 37,371,861 | 6,359,616 | PASS |

## Reproduction

Build the repaired native plugin:

```bash
cmake -S cpp -B /data/tmp/chuxiao/fullgraph-v8-repair-native-build-20260730 \
  -DCMAKE_BUILD_TYPE=Release \
  -DSPINE_SST_CONFIG=/data/feiyang/sst/bin/sst-config
cmake --build /data/tmp/chuxiao/fullgraph-v8-repair-native-build-20260730 -j2
sha256sum /data/tmp/chuxiao/fullgraph-v8-repair-native-build-20260730/libspine_cycle.so
```

The expected plugin SHA-256 is
`eee35f39c118538da5565e497d29b989e5bb492c1368839d424a984c32e2aae9`.

Run one bounded non-monotonic publication case:

```bash
/usr/bin/python3 scripts/run_publication_case.py \
  --materialization-manifest /data/tmp/chuxiao/large_graph_campaign_v1/workloads/sx_askubuntu/materialization_manifest.json \
  --system spine --algorithm weighted_sssp --scenario delete --batch-size 8 \
  --out-dir /data/tmp/chuxiao/large_graph_campaign_v1/noncapacity_v3_repair/delete_u8 \
  --contract configs/contracts/large_graph_publication_campaign_fullgraph_v3.json \
  --sst /data/feiyang/sst/bin/sst \
  --lib-dir /data/tmp/chuxiao/fullgraph-v8-repair-native-build-20260730 \
  --capability-catalog configs/contracts/grasu_regraph_full_graph_capabilities_v7.json \
  --max-cycles 100000000 --source-cohort default \
  --nonmonotonic-sssp-edge-cap 64000 \
  --logical-view update_performance --logical-view update_triggered_compute
```

Revalidate an already-completed PageRank child result by adding
`--reuse-result` to `scripts/run_sst_grasu_regraph_hls_pagerank.py`, then run
the parent publication command with `--reuse-child`.

## Verification

```bash
python3 -m unittest discover -s tests
git diff --check
```

Result: 645 tests pass, 5 tests are skipped, and the diff check is clean.

## Claim boundary

The recovered PageRank rows remain full executable simulations. The repaired
non-monotonic SSSP rows are deliberately bounded 64K real-topology slices
because the current hardware contract cannot rebuild a larger snapshot in one
maintenance launch. They must not be labeled as full-graph delete or full-graph
weight-change results. Full-graph insertion remains supported and unchanged.
