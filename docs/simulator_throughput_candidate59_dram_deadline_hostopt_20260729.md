# Simulator throughput milestone 19: DRAM deadlines and optimized host build

## Scope

This milestone removes repeated host-only polling from the exact DRAMSim3
path and makes the optimized backend reproducible:

- refresh scheduling tracks the next exact refresh deadline instead of
  recomputing a modulo expression every active DRAM cycle;
- completed-read and completed-write queues expose their next return cycle,
  so cycles with no due response do not rescan the queues;
- each DRAM command queue caches its next command-ready cycle. The cache is
  invalidated when a command is inserted or issued and when refresh state
  changes, preserving the original FR-FCFS policy and timing checks; and
- the backend is built with release assertions disabled, LTO,
  `-fno-semantic-interposition`, and `-march=native`. The build script offers
  `--portable-host` to omit the machine-specific flag.

The implementation is distributed as
`patches/dramsim3_deadline_hotpath.patch` and is applied automatically by
`scripts/build_exact_idle_dramsim3_backend.py`. These changes do not alter the
simulated architecture or advance over an unresolved memory event.

## Controlled result

The frozen workload is `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`. Three
Candidate 59 repetitions were compared with the accepted Candidate 52 median.

| System | Candidate 52 median host s | Candidate 59 median host s | Incremental speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 2.654 | 2.534 | 1.047x | 4,778,979 |
| GraSU+ReGraph | 25.425 | 24.181 | 1.051x | 15,310,428 |

The incremental geometric-mean speedup is **1.049x**. Against the original
frozen binary, Candidate 59 is **3.112x** faster for Spine, **4.351x** faster
for GraSU+ReGraph, and **3.680x** faster in geometric mean. This is useful
progress but does not satisfy the frozen 10x objective.

## Exactness gate

All three measured runs pass the fail-closed Candidate 24 comparator. In each
run:

- all pre-existing result fields are identical;
- both complete `result.json` files are byte-identical; and
- all 26 DRAMSim3 JSON files are byte-identical.

Therefore cycles, correctness results, request and byte ledgers, locality,
FIFO and AXI stalls, DRAM commands, activity, and energy are unchanged. A
fourth run rebuilt from a clean DRAMSim3 revision also passes the same gate.

The clean reconstruction reports `status: PASS` and records patch SHA-256
`6dfe02a7104d4705200d73f832b6a7c2009c8968f09d4043a1b7f262accc335f`.
Compact evidence is under
`docs/evidence/simulator_throughput_candidate59_dram_deadline_hostopt_20260729`.

## Validation

The shared-core and GraSU C++ tests pass under CTest. The full Python suite
passes 586 tests with five expected skips. A clean backend reconstruction,
plugin relink, frozen-pair execution, strict equivalence comparison, and
`git diff --check` also pass.

Two explored changes were rejected rather than retained: broad active-DRAM
fast-forward did not reduce wall time despite skipping idle controller cycles,
and dense request histograms were within run noise. Neither appears in this
milestone.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

python3 scripts/build_exact_idle_dramsim3_backend.py \
  --work-root /data/tmp/chuxiao/candidate59-reproduction-backend \
  --install-prefix /data/tmp/chuxiao/candidate59-reproduction-install \
  --jobs 8

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate59-reproduction-backend/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate59-reproduction-install
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst

make -B -C cpp/sst -j8

SPINE_SST_MEMORY_BACKEND=direct_dramsim3_transport \
GRASU_SST_MEMORY_BACKEND=direct_dramsim3_transport \
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/candidate59-reproduction \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_candidate24_direct_transport_provenance_20260728 \
  --candidate-dir /data/tmp/chuxiao/candidate59-reproduction \
  --out-dir /data/tmp/chuxiao/candidate59-reproduction-equivalence \
  --allow-direct-transport
```

## Next step

The next orthogonal candidate is profile-guided optimization trained on both
systems of the frozen pair. After that measurement, profiling must target the
remaining repeated scheduler, AXI evaluate/commit, and ReGraph degree/apply
work. Any cycle skipping remains admissible only when FIFO, arbitration,
response, refresh, and visibility boundaries are proven exactly.
