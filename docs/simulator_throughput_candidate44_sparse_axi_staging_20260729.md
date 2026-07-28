# Simulator throughput milestone 16: sparse AXI issue staging

## Scope

The AXI issue path tracks how many additional beats each active burst stages
during one evaluate phase. Previously it cleared an array proportional to the
number of active bursts on every active cycle, even though at most
`beat_issues_per_cycle` entries can change. The array now retains storage and
clears only the entries touched by the preceding evaluate phase.

This is host-only bookkeeping. Burst selection, round-robin order, admission,
requests, responses, stalls, finite capacities, clocks, and DRAM execution are
unchanged. The optimization is shared by Spine and GraSU+ReGraph.

## Controlled result

Frozen run: `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`, using the normal
`-O3 -DNDEBUG -flto` build and direct DRAMSim3 transport.

| System | Candidate 40 host s | Candidate 44 host s | Incremental speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 2.696 | 2.659 | 1.014x | 4,778,979 |
| GraSU+ReGraph | 27.608 | 26.858 | 1.028x | 15,310,428 |

The incremental geometric-mean speedup is **1.021x**. Against the original
frozen binary, the normal build is now 2.965x faster for Spine, 3.918x faster
for GraSU+ReGraph, and **3.408x** faster in geometric mean. PGO remains an
orthogonal optimization and must be retrained after source changes.

## Exactness gate

The fail-closed comparator against Candidate 24 reports PASS:

- all 356 pre-existing result fields are identical;
- both complete `result.json` files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, correctness, requests, bytes, traces, stalls, DRAM commands,
  activity, and energy counters are unchanged.

The candidate plugin SHA-256 is
`35ca7a40d1a542a6b65ad75e30a7d3768f5c4d375f5ff365cd0b59018fcc55ee`.
Compact evidence is committed under
`docs/evidence/simulator_throughput_candidate44_sparse_axi_staging_20260729`.
Raw evidence remains under `/data/tmp/chuxiao/` in the matching Candidate 44
directories.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate13-reproduction-build-20260728/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate13-reproduction-install-20260728
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst

make -C cpp/sst -j8
cmake --build build/cycle-core -j8
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests

SPINE_SST_MEMORY_BACKEND=direct_dramsim3_transport \
GRASU_SST_MEMORY_BACKEND=direct_dramsim3_transport \
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/candidate44-reproduction \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_candidate24_direct_transport_provenance_20260728 \
  --candidate-dir /data/tmp/chuxiao/candidate44-reproduction \
  --out-dir /data/tmp/chuxiao/candidate44-reproduction-equivalence \
  --allow-direct-transport
```

Validation: 105 shared-core tests, 29 GraSU tests, and 586 Python tests pass;
five Python tests are expected skips. `git diff --check` is clean.
