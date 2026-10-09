# Spine graph edge payload path

Date: 2026-07-24
Branch: `codex/fine-grained-cycle-sim`

## Scope

This milestone migrates Spine level-edge payloads onto the simulated HBM path.
It extends the payload-backed memory work from vertex state to graph level
records:

`SpineL0Maintenance -> graph AXI write payload -> MemoryBackend/SST payload
store -> graph AXI read response -> SpineSplitReader -> AXIS edge word`

The reader still uses the logical level directory to decide which rows, tiles,
and edge slots are occupied. The destination and weight carried to compute now
come from the returned graph-edge payload for each emitted edge.

## Encoding

Spine level edges are encoded as one 64-bit HLS CSR word:

| bits | field |
| --- | --- |
| 63:32 | `dst` |
| 31:16 | `weight` |
| 15:0 | signed `diff` bits |

The source vertex is still recovered from the row/source selected by the
reader, matching the current compact level layout.

## Accepted evidence

The new C++ anti-bypass test `spine_reader_hbm_graph_payload` proves that the
reader consumes returned HBM payload:

1. Run maintenance on a one-edge logical level: `src=0, dst=1, weight=5`.
2. After maintenance drains, overwrite only the graph HBM edge word with
   `src=0, dst=2, weight=2`.
3. Feed the reader source value `10`.
4. Require the emitted edge word to be `dst=2, proposal=12`.

A reader that still used `state.cold_levels` would emit `dst=1, proposal=15`
and fail the test.

Online SST evidence was regenerated for three small acceptance scenarios:

| scenario | cycles | backend requests | graph payload written | graph payload read |
| --- | ---: | ---: | ---: | ---: |
| Amazon L0 exact | 4,608 | 545 | 80 B | 80 B |
| carry + hot | 4,805 | 598 | 24 B | 24 B |
| weighted SSSP | 22,630 | 2,412 | 64 B | `[24, 24, 16, 16, 8, 0]` B per round |

Frozen summaries:

- `docs/evidence/sst_spine_graph_edge_payload_amazon_l0_20260724_summary.json`
- `docs/evidence/sst_spine_graph_edge_payload_carry_hot_20260724_summary.json`
- `docs/evidence/sst_spine_graph_edge_payload_weighted_sssp_20260724_summary.json`

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest tests.test_sst_spine_vertical tests.test_sst_payload_roundtrip

make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 \
  --out-dir results/sst_spine_graph_edge_payload_amazon_l0_20260724 \
  --no-build
python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot \
  --out-dir results/sst_spine_graph_edge_payload_carry_hot_20260724 \
  --no-build
python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp \
  --out-dir results/sst_spine_graph_edge_payload_weighted_sssp_20260724 \
  --no-build
```

## Claim boundary

This closes the emitted graph-edge value bypass for the accepted Spine vertical
paths. Sorted input is closed in
`docs/spine_sorted_input_payload_path_20260724.md`. The whole level directory is
still not payload-complete:

- level occupancy, row enumeration, and tile grouping still consult logical
  containers;
- graph index payload is now explicit and the source bitmap gates row presence,
  but page-base, row-offset, and row-mask fields are not yet decoded into all
  address and control decisions; see
  `docs/spine_graph_index_payload_path_20260724.md`;
- carry edge payload is closed in
  `docs/spine_carry_level_payload_path_20260724.md`, but carry source/row
  semantics still consult logical level metadata;
- reader issue is still one memory task at a time rather than a fully
  pipelined/outstanding HLS loop.

The correct claim is therefore still `structural_execution_driven` with
payload-backed vertex state and graph edge records, not full HLS-cycle
equivalence.
