# D-stage Phase 3D Real Graph Slice Sanity Check

Date: 2026-07-19

## Scope

Phase 3D checks whether the frozen Phase 3C D-stage timing model still tracks
host-runnable workload shapes derived from a real graph. This is a sanity check,
not a full real-graph end-to-end benchmark.

The HLS host does not currently load arbitrary `.mtx` edge lists for this split
kernel path. The new extraction script therefore parses real source slices and
translates each slice into existing host-supported shapes:

- `--multi-source-tile-work`: primary translation. Preserves active-source count
  and approximates per-tile work with equal work per source.
- `--striped-source-tile-work`: primary translation for large replay-fallback
  frontiers where average per-tile work would exceed the current L0 batch limit.
- `--partition-tile-work`: diagnostic aggregate control. Preserves tile work but
  intentionally collapses many active sources into one source, removing replay
  pressure.

The Phase 3C fit was kept frozen:

```bash
results/phase3c_full_partition_analysis_20260719_175848/fit.json
```

## Code Changes

- `scripts/extract_real_graph_slices.py`
  - Parses bare edge lists and MatrixMarket-like graph files.
  - Selects top-degree, dense-window, and stride-sampled source slices.
  - Emits `real_slice_matrix.json`, `real_slice_metrics.csv`, and
    `real_slice_summary.json`.
  - Computes raw slice schedule metrics and translated host-workload schedule
    metrics for coverage and trust classification.
- `scripts/run_hw_dstage_readiness.py`
  - Added `--matrix-json` for externally generated D-stage matrices.
- `tests/test_hw_dstage_readiness.py`
  - Added external matrix JSON loader coverage.
- `tests/test_real_graph_slices.py`
  - Added bare 1-based edge-list extraction coverage.

## Evidence Inputs

Graph:

```bash
/home/chuxiao/ReGraph/dataset/amazon-2008.mtx
```

Parsed graph summary:

- vertices: 735,323
- edges: 5,158,388
- nonzero out-degree sources: 646,766
- max source out-degree: 10
- raw vertex IDs all map to Spine destination partition 0 under
  `VS_PARTITION_SIZE=1,048,576`
- touched cold D-stage tiles: up to 12 under `CONV_TILE_VERTICES=65,536`

Fixed routed HW evidence:

```bash
xclbin: /data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/compact_validation_20260717/hw_134_routed_accepted/xclbin/spine_partitioned_split_e2e.hw.xclbin
xclbin sha256: 57f1459e53145f63e89845d7a694e52db548f90611d9d8cd665a413f67bf12a0
host: /home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
host sha256: aad70a399edec252f013f2094e7d1d5d6c62cb3825cecb3585359e70be49b5b4
HLS repo HEAD: 9069ddffcd25abd7be3929f12f76ed3ba0ff62f4
sim repo starting HEAD: 767019e92313011ba28cc8cc2b3e089447bd88b8
```

## Reproduction Commands

Generate the real graph slice matrix:

```bash
OUT=results/phase3d_amazon_slices_$(date +%Y%m%d_%H%M%S)
python3 scripts/extract_real_graph_slices.py \
  --graph /home/chuxiao/ReGraph/dataset/amazon-2008.mtx \
  --out-dir "$OUT"
```

Run HW:

```bash
HW_OUT=results/phase3d_amazon_slices_hw_$(date +%Y%m%d_%H%M%S)
python3 scripts/run_hw_dstage_readiness.py \
  --matrix-json "$OUT/real_slice_matrix.json" \
  --out-dir "$HW_OUT" \
  --repeats 3 \
  --timeout 240
```

Check translated schedule/counter alignment:

```bash
python3 scripts/compare_dstage_tile_schedule.py --hw-dir "$HW_OUT"
```

Evaluate with the frozen Phase 3C model:

```bash
ANALYSIS_OUT=results/phase3d_amazon_slices_analysis_$(date +%Y%m%d_%H%M%S)
python3 scripts/analyze_phase3b_bottlenecks.py \
  --hw-dir "$HW_OUT" \
  --model-fit results/phase3c_full_partition_analysis_20260719_175848/fit.json \
  --out-dir "$ANALYSIS_OUT" \
  --trusted-threshold-pct 15 \
  --max-threshold-pct 30
```

Run tests:

```bash
python3 -m unittest tests.test_hw_dstage_readiness tests.test_real_graph_slices
```

## Run Evidence

Generated slice directory:

```bash
results/phase3d_amazon_slices_20260719_220628
```

HW directory:

```bash
results/phase3d_amazon_slices_hw_20260719_220659
```

Analysis directory:

```bash
results/phase3d_amazon_slices_analysis_20260719_221003
```

HW status:

- cases: 15
- repeats: 3
- runs: 45
- successful runs: 45

Schedule/counter comparison:

- status: PASS
- schedule samples: 516
- schedule failures: 0
- counter samples: 45
- counter failures: 0

Prediction summary, all cases:

- samples: 15
- median absolute error: 11.523%
- max absolute error: 75.372%
- trusted: 9
- borderline: 5
- untrusted: 1

Prediction summary, primary real-slice translations only
(`avg_tile_work` + `striped_avg_degree`, excluding aggregate controls):

- samples: 12
- median absolute error: 12.889%
- max absolute error: 27.797%
- trusted: 7
- borderline: 5
- untrusted: 0

Prediction summary, aggregate diagnostic controls only:

- samples: 3
- median absolute error: 7.449%
- max absolute error: 75.372%
- trusted: 2
- borderline: 0
- untrusted: 1

## Key Rows

| case | translation | raw active sources | raw edges | translated edges | status | abs error | bottleneck |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| amazon_top64_avg | avg_tile_work | 64 | 640 | 1,152 | trusted | 4.72% | dstage_reader_dominant |
| amazon_top512_avg | avg_tile_work | 512 | 5,120 | 9,216 | trusted | 9.24% | dstage_reader_dominant |
| amazon_top4096_avg | avg_tile_work | 4,096 | 40,960 | 73,728 | trusted | 10.81% | dstage_reader_dominant |
| amazon_densewin4096_active3933_avg | avg_tile_work | 3,933 | 35,133 | 74,727 | trusted | 14.26% | dstage_reader_dominant |
| amazon_stride4096_avg | avg_tile_work | 4,096 | 32,571 | 49,152 | trusted | 8.08% | dstage_reader_dominant |
| amazon_top8192_striped | striped_avg_degree | 8,192 | 81,920 | 81,920 | borderline | 27.70% | dstage_reader_replay_dominant |
| amazon_densewin8192_active7893_striped | striped_avg_degree | 7,893 | 64,658 | 63,144 | borderline | 27.80% | dstage_reader_replay_dominant |
| amazon_stride4096_aggregate | aggregate_one_source | 4,096 | 32,571 | 32,571 | untrusted | 75.37% | maintenance_dominant |

## Conclusions

The translated host workloads exactly match the simulator's structural schedule
for those translated shapes: schedule compare and strict counters are PASS.

For primary real-slice translations, the frozen Phase 3C timing model stays
within the desired 30% max-error bound. The strongest trusted region is the
64-to-4096 active-source, single-partition, multi-tile reader-dominant region.

The 8192-source large-frontier cases are borderline at about 27.7% error. These
are in the replay-fallback region and should be the next calibration target if
we want stronger confidence for very large active frontiers.

Tiny source-count cases remain sensitive to fixed overhead and reader setup
effects. They are useful sanity checks but should not dominate architecture-level
claims.

The aggregate controls show why preserving active-source count matters. Collapsing
thousands of active sources into one source can reduce measured D-stage time from
hundreds of milliseconds to single-digit milliseconds even when the edge count is
similar. For this architecture, real graph performance is driven heavily by
active-record replay and tile sweeping, not just edge count.

This amazon graph only validates the raw-ID single-partition regime. It does not
validate real multi-partition graph behavior, hot/cold behavior, multibatch level
state, or exact `.mtx` host replay.

## Next Gap

The next useful step is to calibrate large-frontier replay-fallback with exact or
closer per-source tile membership. The current `striped` translation preserves
source count, touched tile count, and average fanout, but it does not preserve the
exact per-source tile span distribution from the real graph.
