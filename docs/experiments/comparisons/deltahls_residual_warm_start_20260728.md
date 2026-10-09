# Delta.hls Residual PageRank Warm-Start Integration

Date: 2026-07-28

## Scope

This stage adds an explicit residual PageRank contract without changing the
legacy residual experiments:

- `generic_dangling_l1_cold`: cold rank/residual initialization, dangling-mass
  redistribution, activation threshold `epsilon / N`, and an L1 residual gate;
- `deltahls_sink_free_linf_warm`: sink-free old and new snapshots, a converged
  old rank vector, signed update residuals, activation threshold `epsilon`, and
  an L-infinity residual gate.

The Delta.hls seed is generated inside the SST component as

`r0 = damping * (P_new^T - P_old^T) * p_old`.

The same float32 primary words, auxiliary words, and initial active vertices
are injected into Spine and GraSU+ReGraph. A float32 execution oracle follows
the exact residual rounds. A separate float64 full-PageRank oracle checks the
final mathematical result. Oracle work is not included in simulated cycles.

## Implementation

- `GraphAlgorithmPolicy` owns the contract-dependent threshold and dangling
  semantics.
- `AlgorithmInitialState` is the shared warm-state ABI.
- `SpinePageRankVerticalSliceSystem` filters the first host-active scan to the
  seeded vertices and initializes rank/residual HBM state from the ABI.
- `GraSuReGraphResidualPageRankSystem` initializes the same rank/residual state;
  its source preparation and PMA/ReGraph execution remain execution driven.
- `OnlineMemoryProbe` rejects a Delta.hls run with sinks, records seed and old
  fixed-point evidence, and gates success on both oracles, frontier equality,
  active-edge equality, request conservation, and residual L-infinity.

## Reproduction

Build the plugin:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
make -C cpp/sst -j4
mkdir -p build/deltahls-smoke/spine-dram build/deltahls-smoke/grasu-dram
export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-script-repro-v1/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-script-repro-v1-install
```

Run Spine:

```bash
SPINE_SST_MODE=spine_residual_pagerank \
SPINE_SST_WORKLOAD=$PWD/tests/data/deltahls_sink_free_cycle8_base.slice \
SPINE_SST_UPDATE_WORKLOAD=$PWD/tests/data/deltahls_sink_free_cycle8_update.slice \
SPINE_SST_RESIDUAL_CONTRACT=deltahls_sink_free_linf_warm \
SPINE_SST_PAGERANK_EPSILON=0.0001 \
SPINE_SST_RESIDUAL_MAX_ITERATIONS=256 \
SPINE_SST_MAX_CYCLES=5000000 \
SPINE_SST_CORE_MHZ=150 \
SPINE_SST_OUTPUT=$PWD/build/deltahls-smoke/spine.json \
SPINE_SST_DRAM_OUTPUT=$PWD/build/deltahls-smoke/spine-dram \
scripts/run_sst_exact_idle_dramsim3.sh $PWD/sst/spine_vertical_slice.py
```

Run GraSU+ReGraph K1:

```bash
GRASU_SST_MODE=grasu_regraph_hls_weighted_residual_pagerank \
GRASU_SST_WORKLOAD=$PWD/tests/data/deltahls_sink_free_cycle8_base.slice \
GRASU_SST_UPDATE_WORKLOAD=$PWD/tests/data/deltahls_sink_free_cycle8_update.slice \
GRASU_SST_RESIDUAL_CONTRACT=deltahls_sink_free_linf_warm \
GRASU_SST_PAGERANK_EPSILON=0.0001 \
GRASU_SST_RESIDUAL_MAX_ITERATIONS=256 \
GRASU_SST_MAX_CYCLES=5000000 \
GRASU_SST_CORE_MHZ=150 \
GRASU_SST_PARTITION_VERTICES=16 \
GRASU_SST_COMPUTE_PIPELINES=1 \
GRASU_SST_OUTPUT=$PWD/build/deltahls-smoke/grasu.json \
GRASU_SST_DRAM_OUTPUT=$PWD/build/deltahls-smoke/grasu-dram \
scripts/run_sst_exact_idle_dramsim3.sh $PWD/sst/grasu_regraph_vertical.py
```

## Smoke Evidence

The fixture is an eight-vertex directed cycle. The update replaces `1->2` with
`1->3`; both snapshots remain sink-free.

| Metric | Spine | GraSU+ReGraph K1 |
| --- | ---: | ---: |
| success | true | true |
| cycles | 249,001 | 55,930 |
| residual iterations | 43 | 43 |
| initial active vertices | 2 | 2 |
| expected/executed active edges | 86 | 86 |
| final residual L-infinity | 9.80265e-5 | 9.80265e-5 |
| architecture mismatches | 0 | 0 |
| mathematical mismatches | 0 | 0 |
| frontier match | true | true |
| memory locality/request ledger | true | true |
| backend requests | 20,708 | 23,667 |

The seed L-infinity is `0.10625`; one source row changed, and both old/new sink
counts are zero. The old cycle rank converges in one iteration because its
uniform initial vector is already the fixed point.

Artifact SHA-256 values:

```text
4870fe41597ed63e33df29b3f5b0ae90d5d9651346495424665c3851d6062cd4  build/sst/libspine_cycle.so
c8c28a282ce057d4b2c5250a24fd9ad2bfb4a4489bf772e805c8ed108abd8011  tests/data/deltahls_sink_free_cycle8_base.slice
345f62d9c8bde219f499feb0646d7a6e9c977d93a7e47535a844d10cd8876777  tests/data/deltahls_sink_free_cycle8_update.slice
```

These tiny-graph cycles are structural validation only. Publication performance
claims require the frozen K1 real-data epsilon sweep and the later direct/shared
K4 comparison.
