# Simulator throughput milestone 18: dense memory bookkeeping and payload ranges

## Scope

This milestone removes host-only work from the shared memory path used by both
Spine and normalized GraSU+ReGraph:

- registered-arbiter intent and grant masks use direct dense initiator indexing
  instead of hashing an initiator ID on each admission attempt;
- per-initiator locality cursors and statistics use registered dense lookup;
  the existing public statistics map remains unchanged; and
- payload validity is marked and tested in 64-bit ranges. Fully initialized
  read ranges use a direct copy, while sparse pages retain the original
  byte-wise fill-resolution fallback.

These changes do not alter request generation, arbitration policy, AXI timing,
HBM execution, payload values, locality classification, counters, or traces.

## Controlled result

The frozen workload is `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`. Candidate 46 and
Candidate 52 were built against the same clean DRAMSim3 backend and run in
interleaved order three times.

| System | Candidate 46 median host s | Candidate 52 median host s | Speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 2.716 | 2.654 | 1.023x | 4,778,979 |
| GraSU+ReGraph | 27.308 | 25.425 | 1.074x | 15,310,428 |

The incremental geometric-mean speedup is **1.048x**. Against the original
frozen binary, the measured normal build is 2.971x faster for Spine, 4.138x
faster for GraSU+ReGraph, and **3.506x** faster in geometric mean. PGO remains
orthogonal and must be retrained after source changes.

## Exactness gate

All three Candidate 52 runs pass the fail-closed Candidate 24 comparator. For
each run:

- all 356 pre-existing result fields are identical;
- both complete `result.json` files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, correctness, requests, bytes, locality, stalls, DRAM commands,
  activity, and energy counters are unchanged.

The normal-build plugin SHA-256 is
`7d525416e32a3efff2f6241979abbf75a10a874e80d53eacabf84cb60445e458`.
Compact evidence is under
`docs/evidence/simulator_throughput_candidate52_payload_ranges_20260729`.

## Validation

The shared-core suite (105 tests), GraSU suite (29 tests), and full Python suite
(586 passes, five expected skips) pass. The payload suite includes sparse
fills, explicit-byte precedence, 64-bit validity boundaries, and page-boundary
crossings. `git diff --check` is clean.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

python3 scripts/build_exact_idle_dramsim3_backend.py \
  --work-root /data/tmp/chuxiao/candidate52-reproduction-backend \
  --install-prefix /data/tmp/chuxiao/candidate52-reproduction-install \
  --jobs 8

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate52-reproduction-backend/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate52-reproduction-install
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst

make -B -C cpp/sst -j8
cmake --build build/cycle-core -j8
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests

SPINE_SST_MEMORY_BACKEND=direct_dramsim3_transport \
GRASU_SST_MEMORY_BACKEND=direct_dramsim3_transport \
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/candidate52-reproduction \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_candidate24_direct_transport_provenance_20260728 \
  --candidate-dir /data/tmp/chuxiao/candidate52-reproduction \
  --out-dir /data/tmp/chuxiao/candidate52-reproduction-equivalence \
  --allow-direct-transport
```

## Next step

The cumulative normal-build target is not yet 10x. Remaining wall time is
dominated by dense active-cycle execution: direct DRAMSim3 command processing,
AXI issue/response work, and the ReGraph degree/apply paths. The next milestone
must batch a repeated interval only when its FIFO, arbitration, response, and
refresh boundaries are proven, or exploit independent pseudo-channel work in
parallel without changing response visibility.
