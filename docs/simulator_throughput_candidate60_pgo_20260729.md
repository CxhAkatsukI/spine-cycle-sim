# Simulator throughput milestone 20: retrained two-system PGO

## Scope

This milestone retrains GCC profile-guided optimization after the Candidate 59
source and DRAM backend changes. The frozen training pair executes both Spine
and normalized GraSU+ReGraph so compiler decisions are not specialized to one
architecture. PGO changes host code layout, inlining, and branch placement
only; the normal non-PGO build remains the default.

## Controlled result

Three PGO repetitions were compared with the accepted Candidate 59 normal-build
median on `syn_spread_e512__residual_pagerank`.

| System | Candidate 59 median host s | Candidate 60 PGO median host s | Incremental speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 2.534 | 2.031 | 1.247x | 4,778,979 |
| GraSU+ReGraph | 24.181 | 21.083 | 1.147x | 15,310,428 |

The incremental geometric-mean speedup is **1.196x**. Against the original
frozen binary, Candidate 60 is **3.882x** faster for Spine, **4.991x** faster
for GraSU+ReGraph, and **4.401x** faster in geometric mean. The remaining
factor to the frozen 10x objective is 2.272x.

## Exactness gate

All three PGO runs pass the fail-closed Candidate 24 comparator:

- all pre-existing result fields are identical;
- both complete `result.json` files are byte-identical; and
- all 26 DRAMSim3 JSON files are byte-identical.

Thus modeled cycles, request and byte ledgers, payloads, locality, FIFO and AXI
stalls, DRAM commands, activity, energy, and both correctness oracles are
unchanged. The optimized plugin SHA-256 is
`08a59c8a710d3f4f66b62e86a394757237e930d4d50a998b98bb82c739c21563`.

## Reproduction

The generation and use phases must share one build directory because GCC
encodes output paths in profile filenames.

```bash
cd /home/chuxiao/spine-cycle-sim-publication

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate59-reproduction-backend/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate59-reproduction-install
export PGO_BUILD=/data/tmp/chuxiao/candidate60-pgo-build
export PGO_DATA=/data/tmp/chuxiao/candidate60-pgo-data

make -C cpp/sst pgo-generate -j8 \
  BUILD_DIR="$PGO_BUILD" PGO_PROFILE_DIR="$PGO_DATA"

SPINE_CYCLE_ELEMENT_DIR="$PGO_BUILD" \
SPINE_SST_MEMORY_BACKEND=direct_dramsim3_transport \
GRASU_SST_MEMORY_BACKEND=direct_dramsim3_transport \
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/candidate60-pgo-training \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir "$PGO_BUILD" --no-build

make -C cpp/sst pgo-use -j8 \
  BUILD_DIR="$PGO_BUILD" PGO_PROFILE_DIR="$PGO_DATA"
```

## Interpretation and next step

PGO is an optional simulator-throughput optimization and cannot be reported as
accelerator speedup. The 10x host-runtime target remains open. Subsequent work
must reduce repeated scheduler, AXI, and ReGraph execution while proving event
visibility boundaries; it must also validate host speedups on medium/large
real-data holdouts rather than this synthetic training pair alone.
