# PageRank fallback tile protocol fix

## Failure

The 19,399-vertex, 50,008-edge Full PageRank runtime case completed maintenance
and replayed every edge, then failed before applying any vertex. The graph has
more active source records than the 16,384-entry exact-reader gate, so the
reader used its host-active fallback path.

The fallback emitted `TileBegin.first = tile_base`, but emitted
`TileEnd.first = tile_end - tile_base`. For the single partial tile this changed
the control identity from 0 to 19,399. `SpineSplitPageRankCompute` correctly
rejects a tile whose begin/end identities differ. The SSSP compute path did not
inspect `TileEnd.first`, which is why prior fallback tests passed.

## Fix and validation

Fallback now emits `fallback_tile_base()` in both control words. Edge replay,
forced-dense selection, memory traffic, and tile count are unchanged.

`spine_pagerank_active_gate_fallback` lowers the active-record gate to one and
uses a three-vertex cycle. It therefore reproduces the same fallback protocol
without a long SST run, then requires all three edges and vertices plus the
terminal word to retire successfully.

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j2
./build/cpp/spine_cycle_core_tests spine_pagerank_active_gate_fallback
ctest --test-dir build/cpp --output-on-failure
```

The large real-slice runtime experiment must still be rerun after the SST
plugin is rebuilt. This unit fix alone is not reported as a completed large-run
performance result.
