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

The original failed R19 row remains failure evidence. Its corrected formal
rerun must use a new output directory and pass both correctness oracles before
entering publication aggregates.
