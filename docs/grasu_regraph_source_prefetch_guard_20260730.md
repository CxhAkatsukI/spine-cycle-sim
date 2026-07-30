# GraSU + ReGraph Source-Prefetch Guard

## Failure

The formal R19-32 K4-shared Connected Components run stopped after 31,000,001
cycles with:

```text
logical HBM request is outside the interleaved address map:
channel=1 address=184401920 bytes=64
```

R19-32 has 524,288 vertices, exactly eight 65,536-vertex destination
partitions and exactly 128 4,096-vertex source windows. Address preflight placed
the source-state region at `[180207616, 184401920)`. The rejected request was
therefore exactly one 64-byte beat at the old end, not an aggregate HBM
capacity overflow.

## HLS contract

The original ReGraph little-GS scatter in
`/home/chuxiao/ReGraph/acc_template/kernel_little_gs/acc_scatter.h` keeps two
source windows in a ping-pong buffer. While consuming `pp_read_round`, it emits
requests while `pp_request_round - pp_read_round <= 1`. Consequently, it issues
one speculative 4,096-vertex window after the final useful window. The HBM
wrapper converts each request to `SRC_BUFFER_SIZE / 16` 512-bit reads.

The simulator must retain those reads because they consume HBM bandwidth and
can contend with useful traffic. Suppressing them would make the normalized
GraSU+ReGraph comparator more optimistic than the HLS schedule.

## Repair

`validate_grasu_hbm_address_map` now reserves one
`4096 vertices * 4 bytes = 16384 bytes` look-ahead guard after the second
source-state ping-pong buffer. The guard:

- is included in aggregate interleaved-arena capacity checks;
- is exposed as `source_state.prefetch_guard_bytes` in every run manifest;
- does not add a compute buffer, port, channel, FIFO, or pipeline;
- does not remove or add simulated requests; and
- requires the corresponding HLS/XRT host allocation to include the same
  16 KiB guard when the generated comparator is implemented.

## Boundary validation

An execution-driven K4-shared CC smoke used 65,536 vertices, exactly one full
destination partition, with a reciprocal bridge insertion. It exercised the
same exact-multiple boundary using the frozen full-graph profile and existing
publication plugin.

| Metric | Result |
|---|---:|
| Cycles | 2,270,792 |
| Iterations | 3 |
| Backend requests | 247,316 |
| Source-state read bytes | 98,304 |
| Architecture mismatches | 0 |
| Mathematical mismatches | 0 |
| DRAM request ledger | PASS |
| Source guard | 16,384 B |

Evidence:

```text
/data/tmp/chuxiao/r19-cc-prefetch-guard-smoke/out-v1/result.json
/data/tmp/chuxiao/r19-cc-prefetch-guard-smoke/out-v1/run_manifest.json
```

SHA-256:

```text
result.json       b9fe5586d73240f47c797ebdde04f75c00652d594d6b388fca73dd6a2b070f3c
run_manifest.json 1fb291ea8d2d52df2137d280ee2abd8fbd41e395c6ea346d506067d199beae08
plugin             eee35f39c118538da5565e497d29b989e5bb492c1368839d424a984c32e2aae9
```

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 -m unittest tests.test_grasu_addressing

/usr/bin/python3 scripts/run_sst_connected_components.py \
  --architecture grasu \
  --workload tests/data/connected_components_exact_partition_initial.slice \
  --update-workload tests/data/connected_components_exact_partition_insert.slice \
  --out-dir /data/tmp/chuxiao/r19-cc-prefetch-guard-smoke/out-v1 \
  --profile configs/architectures/grasu_regraph_candidate10_k4_shared_multipart_cc_fullgraph_v7.json \
  --capability-catalog configs/contracts/grasu_regraph_full_graph_capabilities_v7.json \
  --sst /data/feiyang/sst/bin/sst \
  --lib-dir /data/tmp/chuxiao/fullgraph-v8-repair-native-build-20260730 \
  --max-cycles 1000000000 --no-build
```

## Formal R19-32 result

The corrected formal K4-shared run completed the full 29,732,038-edge
reciprocal R19-32 graph. It crossed the original 31,000,001-cycle failure point
and passed at 42,433,681 cycles after 2,172.45 host seconds.

| Metric | Result |
|---|---:|
| Vertices | 524,288 |
| Reciprocal graph records | 29,732,038 |
| Iterations | 2 |
| Backend requests | 15,670,847 |
| Architecture mismatches | 0 |
| Mathematical mismatches | 0 |
| Arbitration ledger | PASS |
| DRAM ledger | PASS |

Evidence:

```text
/data/tmp/chuxiao/large_graph_campaign_v1/formal_v3_r19_cc_guard/
/data/tmp/chuxiao/large_graph_campaign_v1/formal_v3_r19_cc_guard/runs/382bcecb6bbc531de1d8/case_result.json
```

The `case_result.json` SHA-256 is
`38fca20c49dc8b03495e6fd3ba867d1ff340840928374f04d5d6e425258680a1`.
The original failed R19 row remains failure evidence and is excluded from
publication aggregates.

## Empty destination partitions

The completed WikiTalk K4-shared Weighted SSSP child exposed a separate
validator-only boundary. WikiTalk has 18 destination partitions after vertex
reordering, but only five contain live PMA edges. Every dispatched ReGraph
reader, including an empty destination partition, still initializes its two
ping-pong source-cache windows. The execution-driven simulator therefore
reported the following exact request ledger over ten supersteps:

```text
live-partition requests   980
empty-partition requests  13 partitions * 2 requests * 10 steps = 260
total                     1240
```

The old Python validator skipped `None` entries in `partition_max_sources` and
incorrectly expected 980 requests. The child had already completed 649,767,704
cycles with zero architecture and mathematical-oracle mismatches and a closed
210,198,074-request DRAM ledger. Its failure was emitted only after simulation
while checking `source_cache_requests`, `source_cache_lines`, and
`source_cache_lane_writes`.

The validator now charges two initial requests for every empty partition. A
dedicated recovery mode validates an existing immutable `result.json` and DRAM
directory, records their original wall time and SHA-256, and rebuilds only the
child manifest and publication parent result. It cannot run without
`--reuse-completed-weighted-child`, an original profile SHA, and a Git-backed
evidence-only profile amendment. SST is not rerun.

Recovered result:

| Metric | Result |
|---|---:|
| Vertices | 1,140,149 |
| Directed graph records | 1,142,352 |
| Destination partitions | 18 |
| Empty destination partitions | 13 |
| Supersteps | 10 |
| Cycles | 649,767,704 |
| Backend requests | 210,198,074 |
| Source-cache requests | 1,240 |
| Source-cache lines | 317,440 |
| Source-cache lane writes | 2,539,520 |
| Architecture mismatches | 0 |
| Mathematical mismatches | 0 |
| DRAM ledger | PASS |

Evidence:

```text
/data/tmp/chuxiao/large_graph_campaign_v1/formal_v3_weighted_wave/
/data/tmp/chuxiao/large_graph_campaign_v1/formal_v3_weighted_wave/runs/96c048a25bdd97023d02/case_result.json
```

The immutable raw result SHA-256 is
`15de4724a65813f811d63ad89e903cd18f3dca27acd67f3337451024a4768def`.
The recovered parent records
`admission.reused_completed_weighted_child_result=true`, while the child
manifest records `result_recovery.sst_rerun=false`.

## Evidence-pin amendment

Adding the guard changed the packed-addressing contract SHA without changing
any compute, memory-request, or timing parameter. All 23 profiles that cite
that contract, their capability catalogs, and the campaign contracts now pin
the amended dependency hashes. The first post-R19 seven-dataset K4 launch
correctly failed closed before simulation because those transitive pins had
not yet been refreshed. Those zero-cycle failures remain in the campaign event
log; the controlled retry uses the same workload execution IDs after all
path/hash pairs were verified.
