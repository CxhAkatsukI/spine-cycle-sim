# GraSU + ReGraph Runtime-Packed HBM Addressing

## Why this change exists

The fixed-window v4 normalized profiles reserved 16 MiB each for every
partition's binary heads, row offsets, and PMA segments. The windows were
non-aliasing, but the map admitted at most four destination partitions. That
limit was introduced by the simulator profile; it is not the partition limit
of native ReGraph.

An audit of `/home/chuxiao/ReGraph` found that the native host creates one XRT
buffer per scheduled subpartition, assigns it to a CU-connected HBM bank, and
queues subpartitions on the selected CU. Partitions sharing a CU execute in
queue order, while different CU queues may overlap. The source identities are
frozen in
`configs/contracts/grasu_regraph_runtime_packed_addressing_v1.json`.

The packed-v5 profiles therefore replace only the artificial fixed address
windows with a capacity-checked runtime allocation. They do not add compute
pipelines, HBM channels, bandwidth, outstanding requests, FIFO entries, or
ports.

## Layout algorithm

For each destination partition, host preprocessing first constructs the actual
reserved PMA layout. The simulator then computes:

| Region | Per-partition footprint |
|---|---:|
| Binary heads | `8 * reserved_segments` bytes |
| Row offsets | `8 * graph_vertices` bytes |
| PMA on each striped channel | `64 * ceil(reserved_segments / 2)` bytes |

Starting at 16 MiB, binary-head regions, row-offset regions, and PMA regions
are packed in ascending destination-partition order with 4 KiB alignment. Two
source-state ping-pong buffers follow the partition arena; their stride expands
to the padded destination capacity. The Python admission gate and C++ execution
model independently derive the same bases from the same concrete PMA layout.

Every region is checked against the 512 MiB pseudo-channel capacity and against
all other regions on that channel. Overflow or overlap fails before simulation.
The model never wraps or aliases an oversized graph. Such a graph must be
reported as a capacity slice or evaluated with a separately frozen hardware
design.

## Frozen profiles and evidence classes

The generator creates weighted SSSP, Full PageRank, and thresholded residual
PageRank profiles for K1, K2, and K4:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/freeze_grasu_regraph_packed_profiles.py
```

The output capability catalog is
`configs/contracts/grasu_regraph_runtime_packed_capabilities_v5.json`.

- K1 retains the routed compute-worker evidence and adds structural simulator
  evidence for host runtime allocation across more than four partitions.
- K2 and K4 remain simulation-only scalability points.
- The conversion-free GraSU-to-ReGraph interface and all algorithm semantics
  are unchanged.

## Reproduction

Run the focused Python checks:

```bash
python3 -m unittest \
  tests.test_grasu_addressing \
  tests.test_architecture_profiles \
  tests.test_profile_capabilities
```

Build and run the C++ checks:

```bash
cmake -S cpp -B build/cpp -DSPINE_BUILD_TESTS=ON
cmake --build build/cpp -j8
ctest --test-dir build/cpp --output-on-failure
```

Run the complete Python regression:

```bash
python3 -m unittest discover -s tests
```

At this checkpoint, the focused suite passes 29 tests, the complete Python
suite passes 610 tests with 5 environment-dependent skips, and both C++ test
targets pass. Formal large-graph cycles are intentionally not recorded here;
they require the hash-frozen PGO SST plugin and correctness-gated campaign.

## Publication plugin

Candidate85 trains the native-host PGO build on the frozen residual PageRank
case that executes both Spine and GraSU+ReGraph:

```bash
export BUILD=/data/tmp/chuxiao/candidate85-packed-native-pgo-build-20260729
export PGO=/data/tmp/chuxiao/candidate85-packed-native-pgo-data-20260729
export DRAMSIM3=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729

make -C cpp/sst pgo-native-generate -j8 \
  BUILD_DIR="$BUILD" PGO_PROFILE_DIR="$PGO" DRAMSIM3_ROOT="$DRAMSIM3"

SPINE_IDLE_DRAMSIM3_SRC="$DRAMSIM3" \
SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate59-cleanpatch-reproduction-install-20260729 \
SPINE_CYCLE_ELEMENT_DIR="$BUILD" \
SPINE_SST_MEMORY_BACKEND=direct_dramsim3_transport \
GRASU_SST_MEMORY_BACKEND=direct_dramsim3_transport \
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/candidate85-packed-native-pgo-training-20260729 \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir "$BUILD" --no-build

make -C cpp/sst pgo-native-use -j8 \
  BUILD_DIR="$BUILD" PGO_PROFILE_DIR="$PGO" DRAMSIM3_ROOT="$DRAMSIM3"
sha256sum "$BUILD/libspine_cycle.so"
```

The training run reproduces 4,778,979 Spine cycles and 15,310,428
GraSU+ReGraph cycles with zero architecture and mathematical mismatches. The
final plugin SHA-256 is
`c1ed6953ee16b89ff843557dc72eaf22c67f87a34142969c373a7ebd04b229dd`.
