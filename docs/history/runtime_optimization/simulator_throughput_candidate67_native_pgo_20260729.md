# Simulator throughput milestone 21: native host PGO

## Scope

This milestone combines the accepted two-system profile-guided build with
host-specific code generation. `NATIVE_HOST=1` enables `-march=native` and
`-fno-semantic-interposition`; the default build remains portable. These flags
change only simulator host code generation. They do not change the modeled
architecture, event ordering, timing, requests, payloads, counters, or traces.

The Makefile exposes `native`, `pgo-native-generate`, and `pgo-native-use`
targets so generation and use builds retain identical host flags. Both Spine
and normalized GraSU+ReGraph execute in the training workload.

## Controlled result

Three isolated repetitions use the frozen
`syn_spread_e512__residual_pagerank` pair.

| System | Candidate 59 normal median host s | Candidate 60 PGO median host s | Candidate 67 native+PGO median host s | Speedup vs Candidate 60 | Simulated cycles |
|---|---:|---:|---:|---:|---:|
| Spine | 2.534 | 2.031 | 1.856 | 1.094x | 4,778,979 |
| GraSU+ReGraph | 24.181 | 21.083 | 20.305 | 1.038x | 15,310,428 |

The incremental geometric-mean speedup over Candidate 60 is **1.066x**. Against
the original frozen binary, Candidate 67 is **4.248x** faster for Spine,
**5.182x** faster for GraSU+ReGraph, and **4.692x** faster in geometric mean.
The remaining factor to the frozen 10x objective is 2.131x.

The native-only normal build measured 2.440 s for Spine and 23.760 s for
GraSU+ReGraph in median, a 1.028x geometric-mean improvement over Candidate 59.
Most of Candidate 67's gain therefore remains attributable to two-system PGO;
native code generation is a smaller orthogonal improvement.

## Exactness gate

All three Candidate 67 runs pass the fail-closed Candidate 24 comparator:

- all pre-existing result fields are identical;
- both complete `result.json` files are byte-identical; and
- all 26 DRAMSim3 JSON files are byte-identical.

Modeled cycles, request and byte conservation, payloads, locality, FIFO and AXI
stalls, DRAM commands, activity, energy, and both correctness oracles are
unchanged. The optimized plugin SHA-256 is
`8f6019dc107d97e2c38cbb5c8a7806db70bd426ab03d840aa17cedf6318eeb2a`.

## Reproduction

The generation and use phases must use the same build and profile directories.
The resulting binary is specific to the build host CPU.

```bash
cd /home/chuxiao/spine-cycle-sim-publication

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate59-cleanpatch-reproduction-backend-20260729/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate59-cleanpatch-reproduction-install-20260729
export PGO_BUILD=/data/tmp/chuxiao/candidate67-native-pgo-build
export PGO_DATA=/data/tmp/chuxiao/candidate67-native-pgo-data

make -C cpp/sst pgo-native-generate -j8 \
  BUILD_DIR="$PGO_BUILD" PGO_PROFILE_DIR="$PGO_DATA"

SPINE_CYCLE_ELEMENT_DIR="$PGO_BUILD" \
SPINE_SST_MEMORY_BACKEND=direct_dramsim3_transport \
GRASU_SST_MEMORY_BACKEND=direct_dramsim3_transport \
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/candidate67-native-pgo-training \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir "$PGO_BUILD" --no-build

make -C cpp/sst pgo-native-use -j8 \
  BUILD_DIR="$PGO_BUILD" PGO_PROFILE_DIR="$PGO_DATA"
```

## Interpretation and next step

Native PGO is a simulator-throughput optimization, not an accelerator speedup.
The 10x host-runtime objective remains open. The next milestone targets the
per-beat AXI/backend mapping and DRAM transaction bookkeeping that dominates
normalized GraSU+ReGraph, followed by medium/large real-data holdouts.
