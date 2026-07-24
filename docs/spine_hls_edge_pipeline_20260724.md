# HLS-scoped reader edge pipelines

Date: 2026-07-24
Branch: `codex/fine-grained-cycle-sim`

## Delivered behavior

The fine-grained C++ reader now models the three HLS `II=1` edge loops as
bounded execution pipelines rather than `read -> wait -> consume` state pairs:

1. exact range-task construction;
2. exact range-task replay;
3. HOST tiled-fallback replay.

Each active range may issue at most one 64-bit edge read per core cycle. Issued
requests carry transaction IDs and sequence numbers. Responses may complete in
a different order, enter a finite reorder buffer, and retire strictly in HLS
program order. Construction retirement performs destination validation and run
formation. Replay retirement writes the finite reader-compute AXIS and cannot
release its buffer credit until the stream accepts the edge.

The default edge pipeline has 32 request credits and 32 response slots. This
is the edge-word abstraction of the accepted HLS report's two outstanding
reads times a maximum 16-beat burst. Both values are configurable and copied
into every SST result. The separate `memory_request_window` remains one per AXI
initiator, so same-port unpipelined metadata and level-cache tasks remain
ordered while source-distinct HLS bundles may overlap.

## Source and synthesis mapping

The source-following target is `origin/reduce-levels-for-routing` at
`afb8199a2ca8d3fd208b985324bf4d8719e2b839`.

| HLS loop | source directive | cycle model |
| --- | --- | --- |
| `PARTITIONED_BUILD_EXACT_ROW_TASKS` | `PIPELINE II=1` | construction issue + ordered retire |
| `PARTITIONED_EMIT_EDGE_LOOP` | `PIPELINE II=1` | exact and fallback replay issue + AXIS retire |
| family x level cache loops | no pipeline directive | generic serial task path |

The available stable synthesis report records achieved `II=1`, iteration
latency 4, `NUM_READ_OUTSTANDING=2`, and `MAX_READ_BURST_LENGTH=16` for the
replay path. It is evidence for the scheduling shape, not a complete timing
calibration of the newer `afb8199` source.

## Validation evidence

### Orthogonal C++ microbenchmarks

A 256-edge single-range workload uses a 24-cycle mock HBM latency. Only edge
pipeline credits change:

| request/response credits | total cycles | max edge requests in flight |
| ---: | ---: | ---: |
| 1 | 52,341 | 1 |
| 2 | 44,407 | 2 |
| 32 | 37,041 | 29 |

All three runs have identical values, frontier, backend request count, and
traffic bytes. In each run, construction and replay both close at
`256 issued == 256 retired`.

An independent 8,192-edge workload crosses the 4,096-edge compute threshold.
While compute loads the full vertex tile, the 32-entry AXIS fills and produces
4,595 reader-side AXIS stall cycles. All 8,192 construction and replay requests
still retire exactly once and all final distances are correct. This validates
the full causal chain:

`compute pause -> AXIS full -> replay retire stalls -> response credits fill -> request issue stalls`

### Online SST-HBM

The exact Amazon slice passes with zero value/frontier mismatch for both edge
credit settings and exactly 584 backend requests:

| edge credits | cycles | max in flight | construction close | replay close |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 5,816 | 1 | 10/10 | 10/10 |
| 32 | 5,699 | 9 | 10/10 | 10/10 |

The small slice gains only 2.1% because its ten edges are dominated by serial
metadata/control work. The six-round weighted SSSP run also passes, with
per-round construction and replay ledgers `[8, 3, 2, 2, 1, 0]` on both issue
and retire sides. The descriptor-capacity HOST handoff/fallback scenario passes
as well, showing that an aborted construction pipeline drains before fallback
memory work begins.

Machine-readable evidence is in
`docs/evidence/spine_hls_edge_pipeline_20260724_summary.json`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
make -C cpp/sst -j2

python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 --no-build \
  --reader-edge-pipeline-depth 1 \
  --reader-edge-response-capacity 1 \
  --out-dir results/sst_spine_edge_pipeline1_amazon_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 --no-build \
  --reader-edge-pipeline-depth 32 \
  --reader-edge-response-capacity 32 \
  --out-dir results/sst_spine_edge_pipeline32_amazon_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp --no-build \
  --out-dir results/sst_spine_edge_pipeline_weighted_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario fallback_capacity --no-build \
  --out-dir results/sst_spine_edge_pipeline_fallback_20260724
```

The sanitizer build also passes all C++ tests:

```bash
cmake --build build/cycle-core-asan -j2
ctest --test-dir build/cycle-core-asan --output-on-failure
```

Observed sanitizer runtime on this host was 489.64 seconds.

## Remaining claim boundary

This closes the largest reader-side `II=1` scheduling omission, but it does not
yet make the memory path RTL-equivalent. A 64-bit edge is currently represented
as one logical AXI request. HLS may coalesce consecutive loop accesses into
bursts and expose response beats before an entire logical range completes. The
next AXI refinement is therefore explicit burst formation and beat-level
producer delivery, validated against synthesis/interface reports. Maintenance
sorted-edge scans also still need their own loop-scoped issue/consume overlap.
