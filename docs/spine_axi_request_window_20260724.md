# Spine logical AXI request window

Date: 2026-07-24  
Branch: `codex/fine-grained-cycle-sim`

## Scope and claim boundary

This milestone adds a bounded producer-side scoreboard to Spine maintenance
and reader memory tasks. Multiple independent logical requests may be in
flight, responses are matched by transaction ID, overlapping write hazards are
serialized, and issue/completion/stall counters are exported through the C++
and SST result paths.

The implementation is infrastructure for the next loop-accurate model. It is
not yet a source-faithful model of HLS overlap. The default
`memory_request_window=1` preserves conservative phase-serial behavior. Values
greater than one are explicitly an architecture what-if because they permit
coarse tasks from the same phase to overlap even when their enclosing HLS loop
is not pipelined.

## HLS mapping audit

The source-following target is
`origin/reduce-levels-for-routing` at `afb8199a2ca8d3fd208b985324bf4d8719e2b839`.
The SHA-256 of `src/spine_partitioned.hpp` read through `git show` is
`d5c4a2f2c2f384e33808eee4250c0c88208027b3792d46425e1de2ae1d8a06ba`.

The source distinguishes three scheduling scopes:

| HLS scope | Source scheduling | Required simulator behavior |
| --- | --- | --- |
| exact row-task construction | `PARTITIONED_BUILD_EXACT_ROW_TASKS`, `PIPELINE II=1` | one edge request may start per cycle, with ordered payload retirement |
| exact edge replay | `PARTITIONED_EMIT_EDGE_LOOP`, `PIPELINE II=1` | one edge may flow per cycle, subject to HBM and AXIS backpressure |
| 32-family x 11-level cache load | no pipeline pragma on either outer loop | serialize scalar level-cache transactions unless synthesis proves overlap |

The available 2026-07-11 synthesis report independently records achieved
`II=1` for `PARTITIONED_EMIT_EDGE_LOOP`, with iteration latency 4 and a maximum
trip count of 4096:

```text
/data/feiyang/spine-dynamic-graph/tests/test_integration/
  csynth_readmaint_prj/sol/syn/report/
  partitioned_emit_edge_range_tile_Pipeline_PARTITIONED_EMIT_EDGE_LOOP_csynth.rpt
```

That report predates `afb8199`; it validates the replay-loop mechanism, not the
entire latest reader.

## SST what-if evidence

Both runs use the exact same Amazon slice, stable hardware profile, payloads,
and SST-HBM backend. Both pass with zero value and frontier mismatches and
produce exactly 584 backend requests (503 reads and 81 writes).

| request window | cycles | maintenance max in flight | reader max in flight | interpretation |
| ---: | ---: | ---: | ---: | --- |
| 1 | 5,860 | 1 | 1 | conservative compatibility baseline |
| 32 | 2,390 | 6 | 10 | coarse-overlap upper-bound what-if |

The 32-entry setting reduces cycles by 2.45x without changing the functional
or traffic ledger. This proves that producer overlap is performance-critical;
it does not prove that the current HLS achieves 2.45x. DRAM row behavior also
changes with request interleaving, so the what-if changes contention rather
than merely subtracting a fixed latency.

Machine-readable evidence is in
`docs/evidence/sst_spine_axi_request_window_20260724_summary.json`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake -S . -B build/cycle-core -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure

make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 \
  --memory-request-window 1 \
  --out-dir results/sst_spine_memory_window1_amazon_20260724
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 \
  --memory-request-window 32 \
  --out-dir results/sst_spine_memory_window_amazon_20260724
```

## Next acceptance gate

Replace coarse phase overlap with separate issue, response, and ordered-retire
state for each HLS-pipelined loop. Construction must preserve destination order
while allowing outstanding edge reads. Replay must stop retirement when AXIS
is full and propagate that pressure through a finite response queue to request
issue. The unpipelined level-cache loop must remain serial. Tests must show
identical payloads and request bytes, `N + pipeline fill/stalls` scaling for
long edge loops, and sensitivity to HBM latency, request depth, response depth,
and AXIS depth.

This reader-side gate is completed in
`spine_hls_edge_pipeline_20260724.md`. Maintenance loop overlap and beat-level
AXI burst formation remain open.
