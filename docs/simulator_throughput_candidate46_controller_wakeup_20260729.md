# Simulator throughput milestone 17: event-driven ReGraph controller

## Scope

The normalized GraSU+ReGraph controller previously evaluated and committed on
every core cycle while any worker owned a partition. Most calls only polled six
worker `done()` flags and incremented two busy-cycle ledgers. This milestone
adds completion edges to PageRank source preparation, ReGraph apply, and the
HBM wrapper. The controller now wakes only for launch, source-prepare
completion, or a worker completion edge.

Skipped controller invocations do not remove architectural time. The controller
bulk-accounts `pipeline_busy_cycles` and `downstream_busy_cycles` from the
elapsed core-cycle interval and the worker occupancy frozen at the previous
transition. Each commit consumes its own staged action, so sleeping cannot
replay a launch. FIFO, AXI, HBM, arbitration, algorithm, and component ordering
are unchanged.

## Controlled result

Frozen run: `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`, with the normal
`-O3 -DNDEBUG -flto` build and direct DRAMSim3 transport.

| System | Candidate 44 host s | Candidate 46 host s | Simulated cycles |
|---|---:|---:|---:|
| Spine | 2.659 | 2.726 | 4,778,979 |
| GraSU+ReGraph | 26.858 | 26.396 | 15,310,428 |

The G+R wall-clock improvement is 1.017x. The untouched Spine variation shows
that a single short run is noisy, so this milestone does not claim a stable
end-to-end host speedup. Against the original frozen binary, the measured
normal build is 2.893x faster for Spine, 3.986x faster for G+R, and 3.396x in
geometric mean.

The structural result is unambiguous. With one scheduler sample per 1,000 core
cycles, Candidate 40 recorded 15,310 controller evaluate samples and 15,310
commit samples. Candidate 46 records zero samples for both phases, meaning the
controller no longer appears at any periodic sample while still completing all
107 iterations and preserving its busy-cycle ledgers.

## Exactness gate

The fail-closed comparator against Candidate 24 reports PASS:

- all 356 pre-existing result fields are identical;
- both complete `result.json` files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, correctness, requests, bytes, traces, stalls, DRAM commands,
  activity, energy, and controller busy-cycle counters are unchanged.

The candidate plugin SHA-256 is
`3219b035fc4a88def82f93ecc2465f6a632f1f77b88a5bbfcfb5696e197ae134`.
Compact evidence is committed under
`docs/evidence/simulator_throughput_candidate46_controller_wakeup_20260729`.
Raw evidence remains under `/data/tmp/chuxiao/` in the matching Candidate 46
run, equivalence, and profile directories.

## Validation

The shared-core suite (105 tests), GraSU suite (29 tests), and full Python suite
(586 passes, five expected skips) pass. `git diff --check` is clean.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate13-reproduction-build-20260728/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate13-reproduction-install-20260728
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
  --out-dir /data/tmp/chuxiao/candidate46-reproduction \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_candidate24_direct_transport_provenance_20260728 \
  --candidate-dir /data/tmp/chuxiao/candidate46-reproduction \
  --out-dir /data/tmp/chuxiao/candidate46-reproduction-equivalence \
  --allow-direct-transport
```

## Next step

Controller polling is no longer a material target. The dominant remaining work
is active DRAMSim3 clocking, AXI beat processing, and scheduled apply/degree
traffic. The next milestone will add exact next-command timing to DRAMSim3 or
batch a proven uncontended AXI interval; neither path may skip an arbitration,
completion, refresh, or response-visibility boundary.
