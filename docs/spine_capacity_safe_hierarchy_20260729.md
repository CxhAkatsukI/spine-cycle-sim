# Spine capacity-safe hierarchy and resident-graph admission

## Scope

This change fixes two false capacity rejections observed by the publication
campaign without hiding real fixed-capacity failures:

1. maintenance selected the first globally empty level even when that level's
   per-family payload was too small for the incoming run plus occupied lower
   runs; the graph writer then failed after dispatch;
2. resident graphs were partitioned only by the coarse cold destination
   windows, but the simulator omitted the HLS host's measured-indegree hot
   classification. Valid skewed graphs could therefore exceed one cold
   family's capacity before simulation began.

The old campaign failed closed, so no failed row entered performance results.
Representative failures were `wiki_talk_temporal` residual PageRank at
1,011,592 cycles (`Spine level writer exceeds target edge capacity`) and
`soc_pokec` weighted SSSP during resident preload.

## Paper and HLS contract

Delta.hls specifies a ratio-2 hierarchy with `Q = 2^17`, 11 provisioned
levels, 16 destination families, a shared target level, and explicit capacity
overflow. The current HLS layout has one necessary physical detail that makes
a literal first-empty reduction insufficient under skew:

- L0 reserves `Q` records in every family so an arbitrary legal batch can be
  concentrated in one destination family;
- level `l > 0` reserves `ceil(Q * 2^l / 16)` records per family.

Consequently L0 is larger than L1, L2, and L3 per family. The selected target
is now the first empty level whose per-family capacity covers the conservative
raw input count plus every occupied lower-level count. Undersized empty levels
are skipped; occupied levels are never overwritten. No suitable level remains
an explicit pre-writer overflow.

The resident-graph policy mirrors the host implementation in
`tests/test_integration/host_split.hpp` and the R19 path in
`host_partitioned_rmat24_benchmark.cpp`:

1. measure actual destination indegree;
2. compute cold-window loads;
3. if a cold family exceeds the aggregate fixed-family capacity, sort
   destinations by descending indegree (destination ID breaks ties);
4. promote destinations through the exact HLS hash into 16 hot shards until
   every cold family is at or below the L9 target;
5. require each hot shard to fit the L10 physical cap;
6. preload all families into L10 when this contract fits.

For a balanced graph that does not trigger hot promotion but has a family
larger than L10 and no larger than the aggregate hierarchy, the simulator uses
an explicitly reported multilevel bootstrap fallback. This is a conservative
simulator extension, not native-HLS evidence. Formal result JSON distinguishes
`resident_top_level_preload` from `resident_multilevel_fallback`.

## Implementation

- `cpp/src/spine_l0.cpp`
  - `classify_spine_resident_snapshot()` implements the measured-indegree
    classifier and records the physical admission ledger;
  - `preload_spine_resident_snapshot()` synchronizes the generated hot bitmap
    with `SpineL0Config`, uses L10 preload for the HLS path, and uses bounded
    multilevel packing only for the labeled fallback;
  - the target selector uses raw dispatch-family counts, matching
    `family_begin` in HLS, rather than coalesced or unique counts.
- `cpp/sst/online_memory_probe.cpp`
  - dynamic SSSP, full/residual PageRank, and connected components all use the
    same resident classifier and preload path;
  - result JSON reports hot vertices/edges, maximum cold/hot family load,
    capacities, and preload policy.
- `spine_cycle_sim/models/spine.py`
  - the legacy Python timing layer uses the same capacity-safe target rule and
    raw family input bound.
- HLS worktree `/data/tmp/chuxiao/spine-hls-capacity-aware-target`
  - `src/spine_partitioned.hpp` selects the capacity-safe target from HBM
    metadata and one-pass `family_begin` counts before launching a writer.

Two tempting late fixes were deliberately rejected during review. Retargeting
inside `build_family_outputs()` is too late: the consumed-level mask, metadata
scan, writer schedule, and physical target addresses have already been chosen,
so it can overwrite an occupied higher level and omit selector timing. Likewise,
the local `GraSuPmaLayout` must not infer a global destination-partition count
from maximum destination ID; cross-dst19 graphs use
`GraSuPartitionedPmaLayout`, whose PMA words carry partition-local IDs.

## What remains a real rejection

- graph vertices exceed the frozen `MAX_N` profile;
- one destination's indegree exceeds one L10 hot-shard capacity under the
  current single-home hash policy;
- the classifier cannot fit all cold and hot physical families;
- one update batch exceeds `Q`;
- no capacity-safe empty target remains after accounting for occupied levels.

These cases must be labeled unsupported/profile-capacity failures. Enlarging a
vector in the simulator would not make the frozen accelerator implementable.

## Real-graph regression evidence

The logic-identical Candidate91 admission build was exercised on the complete
materialized `soc_pokec` directed weighted workload, not a compact slice. The
1,632,803-vertex, 44,603,928-edge snapshot completed resident classification
and preload before the deliberately tiny `max_cycles=1` limit stopped
execution:

- policy: `hls_degree_v1_promoted`;
- 646,007 hot destinations;
- 37,694,419 hot edges and 6,909,509 cold edges;
- maximum cold-family load 4,194,300, below the L9 target 4,194,304;
- maximum hot-shard load 2,376,280, below the L10 cap 8,388,608;
- all resident families placed at L10; no multilevel fallback.

The old `wiki_talk_temporal` residual PageRank run failed in its writer at
1,011,592 cycles. Candidate92 crossed that point and reached the deliberate
2,000,000-cycle stop without a writer or capacity error. These are admission
and progression regressions, not completed performance rows; neither enters a
speedup aggregate.

Candidate92 is the formal native+PGO plugin. It differs from Candidate91 only
by emitting the selector/classification ledger consistently in every Spine
algorithm result and labels non-resident runs `not_applicable`. Its training
pair remains cycle-identical (`4,778,979` Spine and `15,310,428`
GraSU+ReGraph cycles). The pinned SHA-256 is
`88d44610461b876ec6617b705e338ed866f4ca18c41e1925bee4f8a26fcc3854`.

Raw evidence is under
`/data/tmp/chuxiao/candidate91-hot-classifier-validation-20260729/soc_pokec`
and
`/data/tmp/chuxiao/candidate92-capacity-validation-20260729/wiki_talk_writer_progress`.

## Reproduction

```bash
cmake -S . -B /data/tmp/chuxiao/capacity-tests -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS='-Werror'
cmake --build /data/tmp/chuxiao/capacity-tests -j16
ctest --test-dir /data/tmp/chuxiao/capacity-tests --output-on-failure -j2
python3 -m unittest discover -s tests

make -C cpp/sst native -j16 \
  BUILD_DIR=/data/tmp/chuxiao/capacity-native \
  DRAMSIM3_ROOT=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729
```

Focused C++ tests cover undersized-level skipping, raw-count conservatism,
automatic hot promotion, exact L10 placement, bounded multilevel fallback,
super-hub rejection, and pre-writer hierarchy exhaustion.

The HLS host unit test requires the Vitis `ap_int.h` environment:

```bash
make -C tests/test_integration host_partitioned_shared_maintenance_test
tests/test_integration/host_partitioned_shared_maintenance_test
```

The local account cannot access `/var/run/docker.sock`, so that HLS-host
compile must be run in the existing Vitis container before the HLS branch is
claimed compile-validated. The simulator C++ and Python suites do not depend
on that container.
