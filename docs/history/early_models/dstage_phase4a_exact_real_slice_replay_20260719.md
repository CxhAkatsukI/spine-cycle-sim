# D-stage Phase 4A Exact Real Slice Replay

Date: 2026-07-19

## Scope

Phase 4A upgrades the Phase 3D real graph sanity check from structural
translation to exact single-batch real-slice replay.

Confirmed boundary:

- No kernel change.
- No xclbin rebuild.
- HLS host and simulator read the same slice files.
- One update batch plus one D-stage convergence pass.
- Single-partition amazon-2008 raw-ID regime first.
- Schedule/counter alignment is the primary acceptance criterion.
- Timing is evaluated with the frozen Phase 3C fit, without refitting.

## Slice Format

The shared slice file is a text edge list with comment metadata:

```text
# spine_real_slice_version=1
# case=amazon_top4096_exact
# graph=/home/chuxiao/ReGraph/dataset/amazon-2008.mtx
# selector=top4096
# vertices=735323
# id_offset=1
# raw_edges=40960
# active_sources=4096
# columns=src dst weight diff
2 3 1 1
2 4 1 1
```

Rows are zero-based `src dst weight diff`. `weight` and `diff` are parsed by the
HLS host; the simulator coalesces duplicate `(src,dst)` records using the same
min-weight and diff-sum rule as the host reference path.

The `vertices` header is required for exact D-stage tile sizing. Inferring the
vertex count from a slice's max vertex ID underestimates the final tile size and
causes tile schedule mismatches.

## Code Changes

Simulator repo:

- `scripts/extract_real_graph_slices.py`
  - Still emits the Phase 3D translated matrix.
  - Now also emits exact slice files under `exact_slices/`.
  - Emits `exact_slice_matrix.json` with `--edge-list-slice <slice_file>` cases.
  - Emits `exact_slice_metrics.csv` with exact raw schedule features.
- `scripts/compare_dstage_tile_schedule.py`
  - Added `--edge-list-slice` workload reconstruction.
  - Reads slice metadata and exact edge rows.
  - Coalesces duplicate updates using host-equivalent semantics.
- `tests/test_real_graph_slices.py`
  - Covers exact slice generation and schedule-compare loading.

HLS host repo:

- `tests/test_integration/host_partitioned_csr_e2e_smoke.cpp`
  - Added `--edge-list-slice <slice_file>`.
  - Reads the shared slice format into `PartitionedCsrEdgeRef`.
  - Uses the `vertices` metadata as `num_vertices_override`.
  - Leaves kernel arguments and xclbin unchanged.

## Evidence Inputs

Graph:

```bash
/home/chuxiao/ReGraph/dataset/amazon-2008.mtx
```

Parsed graph:

- vertices: 735,323
- edges: 5,158,388
- nonzero out-degree sources: 646,766
- max source out-degree: 10
- raw IDs map to Spine destination partition 0
- exact slices touch up to 12 D-stage tiles

Fixed routed xclbin:

```bash
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/compact_validation_20260717/hw_134_routed_accepted/xclbin/spine_partitioned_split_e2e.hw.xclbin
sha256: 57f1459e53145f63e89845d7a694e52db548f90611d9d8cd665a413f67bf12a0
```

Rebuilt host:

```bash
/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
sha256: d1b48172f1f6422c72e285e3cc8bc85aa9be8b1bd208688eb0b12f5d7aeed383
```

Starting commits:

- simulator: `ba752af7c306747ddf2adebcfca80c2743607eac`
- HLS host repo: `9069ddffcd25abd7be3929f12f76ed3ba0ff62f4`

## Reproduction Commands

Generate exact slices and matrices:

```bash
OUT=results/phase4a_amazon_exact_slices_$(date +%Y%m%d_%H%M%S)
python3 scripts/extract_real_graph_slices.py \
  --graph /home/chuxiao/ReGraph/dataset/amazon-2008.mtx \
  --out-dir "$OUT"
```

Build the HLS host only:

```bash
cd /home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration
source /opt/xilinx/xrt/setup.sh
make host_partitioned_csr_e2e_smoke
```

Run exact-slice HW:

```bash
HW_OUT=results/phase4a_amazon_exact_slices_hw_$(date +%Y%m%d_%H%M%S)
python3 scripts/run_hw_dstage_readiness.py \
  --matrix-json "$OUT/exact_slice_matrix.json" \
  --out-dir "$HW_OUT" \
  --repeats 3 \
  --timeout 240 \
  --host-exe /home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
```

Compare exact schedule and counters:

```bash
python3 scripts/compare_dstage_tile_schedule.py --hw-dir "$HW_OUT"
```

Analyze timing with the frozen Phase 3C model:

```bash
ANALYSIS_OUT=results/phase4a_amazon_exact_slices_analysis_$(date +%Y%m%d_%H%M%S)
python3 scripts/analyze_phase3b_bottlenecks.py \
  --hw-dir "$HW_OUT" \
  --model-fit results/phase3c_full_partition_analysis_20260719_175848/fit.json \
  --out-dir "$ANALYSIS_OUT" \
  --trusted-threshold-pct 15 \
  --max-threshold-pct 30
```

Run simulator tests:

```bash
python3 -m unittest discover -s tests
```

## Final Run Evidence

Slice output:

```bash
results/phase4a_amazon_exact_slices_20260719_223554
```

HW output:

```bash
results/phase4a_amazon_exact_slices_hw_20260719_224034
```

Analysis output:

```bash
results/phase4a_amazon_exact_slices_analysis_20260719_224254
```

HW run status:

- cases: 12
- repeats: 3
- runs: 36
- successful runs: 36

Schedule/counter comparison:

- status: PASS
- schedule samples: 408
- schedule failures: 0
- counter samples: 36
- counter failures: 0

Frozen-model timing summary:

- samples: 12
- median absolute error: 18.839%
- max absolute error: 36.022%
- trusted: 4
- borderline: 5
- untrusted: 3

## Key Rows

| case | active sources | edges | touched tiles | full tiles | fallback | median conv ms | status | abs error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| amazon_top1_exact | 1 | 10 | 10 | 0 | 0 | 0.579 | trusted | 8.84% |
| amazon_top64_exact | 64 | 640 | 12 | 0 | 0 | 6.885 | trusted | 14.58% |
| amazon_stride512_exact | 512 | 4,079 | 12 | 0 | 0 | 54.143 | trusted | 14.01% |
| amazon_top512_exact | 512 | 5,120 | 12 | 0 | 0 | 54.443 | borderline | 21.80% |
| amazon_top4096_exact | 4,096 | 40,960 | 12 | 1 | 0 | 438.297 | borderline | 24.33% |
| amazon_stride4096_exact | 4,096 | 32,571 | 12 | 0 | 0 | 435.328 | borderline | 15.52% |
| amazon_densewin4096_active3933_exact | 3,933 | 35,133 | 12 | 1 | 0 | 451.005 | untrusted | 34.00% |
| amazon_top8192_exact | 8,192 | 81,920 | 12 | 12 | 1 | 942.320 | untrusted | 31.40% |
| amazon_densewin8192_active7893_exact | 7,893 | 64,658 | 12 | 12 | 1 | 948.866 | untrusted | 36.02% |

## Conclusions

Phase 4A achieved the structural goal. The same exact real slice files are read
by the HLS host and the simulator, and schedule/counter comparison is fully PASS.

The frozen Phase 3C timing model is less accurate on exact real slices than on
Phase 3D translated slices. The main reason is no longer input mismatch; exact
real slices expose concentrated per-tile work and real per-source tile membership.
The model underpredicts:

- replay-fallback large frontier cases near 8k active sources;
- mixed fast/full cases where one real tile is much denser than the rest;
- reader-dominant cases with high clipped-range counts.

This is a useful result: it moves the gap from "maybe our input is artificial" to
"the real schedule is correct, and the timing model now needs a reader/replay
shape term for exact real graph distributions."

## Next Gap

The next calibration target should be exact real-slice timing features, especially:

- per-tile clipped-range distribution;
- max tile work versus total tile work;
- full-tile plus fast-tile mixed cases;
- replay-fallback with exact source/tile membership.

We should not claim final real-workload timing accuracy yet. We can claim exact
real-slice structural replay is working and has revealed the next timing-model
bottleneck.
