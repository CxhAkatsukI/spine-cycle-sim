# Simulator throughput milestone 12: exact profile-guided build

## Scope

This milestone applies GCC profile-guided optimization (PGO) to the SST
element. It changes host code layout, inlining, and branch placement only. It
does not change the modeled accelerator, event order, timing, FIFO capacity,
AXI/HBM behavior, trace, activity ledger, or energy accounting.

The training workload is the frozen
`syn_spread_e512__residual_pagerank` pair from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`. Both Spine and
normalized GraSU+ReGraph execute during training so the profile does not
specialize for only one architecture. The normal non-PGO build remains the
default; `pgo-generate` and `pgo-use` are explicit Makefile targets.

## Controlled result

| System | Original host s | Candidate 24 host s | PGO host s | PGO incremental | Cumulative |
|---|---:|---:|---:|---:|---:|
| Spine | 7.884 | 2.790 | 2.267 | 1.230x | 3.478x |
| GraSU+ReGraph | 105.218 | 28.327 | 25.456 | 1.113x | 4.133x |

The incremental two-system geometric-mean speedup is **1.170x**. The
cumulative geometric mean from the frozen original binary is **3.791x**. The
remaining factor to the final 10x medium/large acceptance threshold is
2.638x; this single synthetic probe does not satisfy that gate.

Simulated architecture time is unchanged: Spine remains at 4,778,979 cycles
and GraSU+ReGraph remains at 15,310,428 cycles. The reported architectural
speedup therefore also remains unchanged.

## Exactness gate

The fail-closed comparator against Candidate 24 reports PASS:

- all 356 pre-existing result fields are identical;
- both complete `result.json` files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, correctness, requests, bytes, locality, stalls, DRAM commands,
  activity, and energy counters are unchanged.

The optimized plugin SHA-256 is
`a69465bfbe45f213a1599f137e5d342302147a807d4c8b47f272f727eb614ec4`.
It was built with GCC 15.2.0 from source commit `bffb69f`. The linked patched
DRAMSim3 SHA-256 remains
`3831d532874c688dadca64f8fed988295943fff500ff7ec6c48fb00f0d3adb94`.

Compact evidence is committed under
`docs/evidence/simulator_throughput_candidate32_pgo_20260729`. Raw runs remain
under `/data/tmp/chuxiao/`:

- training: `simulator_throughput_pgo_training_run_20260729`;
- candidate: `simulator_throughput_candidate32_pgo_20260729`;
- equivalence: `simulator_throughput_candidate32_pgo_20260729_equivalence`;
- profile data: `spine_cycle_pgo_data_20260729`; and
- plugin: `spine_cycle_pgo_train_20260729/libspine_cycle.so`.

## Reproduction

The generation and use phases must share the same `BUILD_DIR`; GCC encodes the
output object path in the profile filenames.

```bash
cd /home/chuxiao/spine-cycle-sim-publication

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate13-reproduction-build-20260728/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate13-reproduction-install-20260728
export PGO_BUILD=/data/tmp/chuxiao/spine_cycle_pgo_reproduction
export PGO_DATA=/data/tmp/chuxiao/spine_cycle_pgo_reproduction_data

make -C cpp/sst pgo-generate -j8 \
  BUILD_DIR="$PGO_BUILD" PGO_PROFILE_DIR="$PGO_DATA"

SPINE_CYCLE_ELEMENT_DIR="$PGO_BUILD" \
SPINE_SST_MEMORY_BACKEND=direct_dramsim3_transport \
GRASU_SST_MEMORY_BACKEND=direct_dramsim3_transport \
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/simulator_throughput_pgo_reproduction_training \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir "$PGO_BUILD" --no-build

make -C cpp/sst pgo-use -j8 \
  BUILD_DIR="$PGO_BUILD" PGO_PROFILE_DIR="$PGO_DATA"
```

PGO speedup is compiler-, CPU-, and workload-dependent. It is a simulator
throughput optimization, not an accelerator optimization, and must not be
used as an architectural performance claim. The next milestone must obtain a
structural runtime reduction and validate it across medium/large real-data
holdouts and R19 gates.
