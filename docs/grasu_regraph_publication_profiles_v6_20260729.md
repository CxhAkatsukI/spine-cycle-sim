# GraSU+ReGraph publication profiles v6

## Frozen comparison boundary

The publication comparison uses three systems on the same 150 MHz simulator
clock and the same 32-channel, 64-byte-line direct DRAMSim3 HBM platform:

- Spine Candidate10 opt-v2 is the primary projected accelerator.
- GraSU+ReGraph K1 is the single-pipeline normalized baseline.
- GraSU+ReGraph K4-shared is the primary multi-partition competitor. Four
  partition frontends share one merger, apply path, and HBM downstream, so
  contention and backpressure remain visible.

The older direct K4 profiles instantiate four independent downstream paths.
They are retained only as a theoretical no-contention upper bound and are
ineligible for headline aggregates. The conversion-free GraSU-to-ReGraph
handoff is common to K1 and K4-shared; no host conversion time is hidden.

Weighted SSSP, Full PageRank, and thresholded residual PageRank inherit the
packed-v5 algorithm models. The packed-v6 profiles add the resource-constrained
K4-shared organization and Connected Components. CC treats each reciprocal
edge pair as unweighted topology for min-label Map/Reduce while preserving the
exact weighted records in GraSU's PMA update storage. Reciprocal directions may
therefore carry different weights without changing connectivity.

CC is simulator-executable and dual-oracle checked, but its Map/Reduce datapath
does not yet have matching synthesized HLS. This limitation is reported as
simulation-only rather than presented as implementation evidence.

Regenerate all six profiles and the capability catalog deterministically:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/freeze_grasu_regraph_publication_profiles.py
git diff --check
```

## Candidate86 plugin

Candidate86 retrains native-host PGO after the CC topology correction. Rebuild
it with the same two-system residual-PageRank training workload used for prior
publication plugins:

```bash
export BUILD=/data/tmp/chuxiao/candidate86-cc-unweighted-native-pgo-build-20260729
export PGO=/data/tmp/chuxiao/candidate86-cc-unweighted-native-pgo-data-20260729
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
  --out-dir /data/tmp/chuxiao/candidate86-cc-unweighted-native-pgo-training-20260729 \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir "$BUILD" --no-build

make -C cpp/sst pgo-native-use -j8 \
  BUILD_DIR="$BUILD" PGO_PROFILE_DIR="$PGO" DRAMSIM3_ROOT="$DRAMSIM3"
sha256sum "$BUILD/libspine_cycle.so"
```

The training execution reproduces 4,778,979 Spine cycles and 15,310,428
GraSU+ReGraph cycles with zero architecture-oracle and mathematical-oracle
mismatches. The frozen plugin SHA-256 is
`1cc810e3dbfcea9c55aff94cecfc601d762a732f8491d9f17caf8fcbb9e57527`.
PGO changes simulator wall time only; it does not change simulated cycles.

## Real-graph CC admission

AskUbuntu provides the first full reciprocal real-graph admission case:
515,281 vertices, 679,246 physical edge records, and eight reciprocal insertion
mutations. Candidate86 produced the same final label-vector hash
`e45481258c1c9d58f1d5bfaea5d805faf3a8c096b6f2c06999041a1bc9962c99`
for all three systems, with zero mismatches and closed DRAM ledgers.

| System | Simulated cycles | Simulated E2E | Host wall time |
|---|---:|---:|---:|
| Spine | 2,183,667 | 14.558 ms | 41.81 s |
| GraSU+ReGraph K1 | 48,572,180 | 323.815 ms | 375.31 s |
| GraSU+ReGraph K4-shared | 14,354,646 | 95.698 ms | 133.95 s |

These values are admission evidence, not a final aggregate. They establish
that K4-shared actually executes eight destination partitions with four
frontends and shared-downstream contention instead of applying an arithmetic
4x speedup to K1.
