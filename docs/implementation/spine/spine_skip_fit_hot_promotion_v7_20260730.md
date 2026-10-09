# Spine skip-fit hot-promotion baseline (formal-v7)

## Scope

Formal-v7 fixes a host-placement error in all three Spine classifiers. The old
global descending-degree loop could promote a destination from a cold
partition that was already at or below its target. Such a promotion could
consume a hot shard's fixed capacity without reducing the overflowing cold
partition, producing a false capacity rejection on Orkut-scale input.

The corrected loop preserves the global candidate order but skips a candidate
when its own cold partition is already within the target. It does not change
the number of families, levels, partitions, HBM channels, shard hash, FIFO
depth, AXI behavior, or any capacity.

The aligned implementations are:

- `spine_cycle_sim/sst_binding.py::_spine_automatic_hot_vertices`;
- `spine_cycle_sim/models/spine.py::classify_hot_cold`;
- `cpp/src/spine_l0.cpp::classify_spine_resident_snapshot`;
- HLS host helper
  `tests/test_integration/host_split.hpp::partitioned_classify_hot_cold_from_indegree`.

The simulator source revision is
`c22a59a3369a128faa116896d4d801f9698ffe52`. The HLS host-helper revision is
`867bee49e483950a82d69d3f3d8b0661ccbef544` on
`codex/skip-fit-hot-promotion`.

## Frozen artifact

Build the native plugin from the simulator revision:

```bash
make -C cpp/sst native -j16 \
  BUILD_DIR=/data/tmp/chuxiao/spine-skip-fit-hot-native-20260730 \
  DRAMSIM3_ROOT=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729
sha256sum \
  /data/tmp/chuxiao/spine-skip-fit-hot-native-20260730/libspine_cycle.so
```

The required digest is
`1c0b0a9adb245e919e77cedb39b731551befc1f0ca4101a519dce176d9edf057`.
The frozen contract is
`configs/contracts/large_graph_publication_campaign_fullgraph_v7.json`.

Regenerate it without editing JSON by hand:

```bash
python3 scripts/freeze_large_graph_fullgraph_contract.py \
  --source-contract configs/contracts/large_graph_publication_campaign_fullgraph_v6.json \
  --plugin /data/tmp/chuxiao/spine-skip-fit-hot-native-20260730/libspine_cycle.so \
  --output configs/contracts/large_graph_publication_campaign_fullgraph_v7.json \
  --contract-id large_graph_publication_campaign_fullgraph_v7_20260730 \
  --milestone fullgraph_v11_skip_fit_hot_native_o3_lto \
  --source-revision c22a59a3369a128faa116896d4d801f9698ffe52 \
  --behavior-transition automatic_hot_promotion_skips_already_fit_cold_partitions \
  --hls-reference-branch codex/skip-fit-hot-promotion \
  --hls-reference-revision 867bee49e483950a82d69d3f3d8b0661ccbef544 \
  --hls-reference-symbol partitioned_classify_hot_cold_from_indegree \
  --prior-contract-reuse 'v6 Spine rows are reusable only when resident_hot_edges is zero; affected rows require an identical-case v7 successor with identical final state; GraSU+ReGraph behavior is unchanged'
```

## Result transition

This is an HLS behavior correction, not a host-runtime-only plugin rebuild.
The analysis therefore applies a fail-closed transition:

- a v6 Spine row with `resident_hot_edges == 0` remains eligible;
- a v6 Spine row with `resident_hot_edges > 0` is invalidated;
- an invalidated row is replaced only by a v7 result with identical case and
  identical final state;
- GraSU+ReGraph rows are unaffected.

This rule is conservative: it can request a rerun even when all old promoted
vertices happened to come from overflowing partitions, but it cannot silently
reuse a row whose placement may have changed.

## Validation

Run the unit and HLS-host tests:

```bash
python3 -m unittest tests.test_sst_memory_binding tests.test_spine_sim \
  tests.test_large_graph_campaign tests.test_plugin_equivalence \
  tests.test_publication_analysis
cmake --build /data/tmp/chuxiao/candidate88-capacity-fix-tests-build-20260729 -j16
ctest --test-dir \
  /data/tmp/chuxiao/candidate88-capacity-fix-tests-build-20260729 \
  --output-on-failure
make -C /data/tmp/chuxiao/spine-hls-skip-fit-hot-promotion/tests/test_integration \
  host_partitioned_csr_model_test
/data/tmp/chuxiao/spine-hls-skip-fit-hot-promotion/tests/test_integration/host_partitioned_csr_model_test
```

The first formal-v7 canary replays the exact AskUbuntu weighted-SSSP execution
`cbd2b8928cb1c52432db`. Relative to v6 it has identical case identity, final
state, 62,331 cycles, backend traffic, and DRAM ledger. Its machine-readable
audit is `docs/evidence/spine_skip_fit_hot_v7_canary_20260730.json`.

Orkut remains a required large affected case. It must be run with the v7
contract and plugin under the campaign memory circuit breaker; a successful
unit test or canary is not a substitute for that result.

The first affected successor is the full directed Pokec weighted-SSSP case
`a481b5d34abacf23343c`. Relative to v6, the corrected classifier reduces
resident hot edges from 37,694,419 to 36,767,229 while preserving exact case
identity and final state. Device time changes from 123,744 to 123,762 cycles
(+18 cycles, +0.0145%). Both correctness oracles and all request/response/DRAM
ledgers pass. The machine-readable transition record is
`docs/evidence/spine_skip_fit_hot_v7_pokec_successor_20260730.json`.

The full reciprocal StackOverflow connected-components successor
`fe200a697fdba56a2251` provides a second affected algorithm and topology.
Resident hot edges fall from 27,172,463 to 24,204,074, exact case identity and
final state are preserved, and cycles fall from 25,547,188 to 25,478,996
(-68,192 cycles, -0.267%). Its dual-oracle and conservation evidence is in
`docs/evidence/spine_skip_fit_hot_v7_stack_cc_successor_20260730.json`.

The full directed LiveJournal weighted-SSSP successor
`e0e70d282abd77e5201f` extends the transition evidence to a third topology.
Resident hot edges fall from 70,682,914 to 66,855,991 (3,826,923 fewer), while
exact case identity, final state, and 294,699 device cycles are unchanged. Both
correctness oracles and all request/response/DRAM ledgers pass. Its
machine-readable transition record is
`docs/evidence/spine_skip_fit_hot_v7_livejournal_successor_20260730.json`.

The full directed LJournal2008 weighted-SSSP successor
`980c084e249992cc626c` covers 99,028,542 stored edges. Resident hot edges fall
from 78,431,993 to 75,173,628 (3,258,365 fewer), while exact case identity and
final state are preserved. Device cycles change from 91,549 to 91,575
(+26 cycles, +0.0284%). Both correctness oracles and all
request/response/DRAM ledgers pass. Its machine-readable transition record is
`docs/evidence/spine_skip_fit_hot_v7_ljournal2008_successor_20260730.json`.
