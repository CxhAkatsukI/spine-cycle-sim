# Simulator throughput milestone 11: exact direct DRAMSim3 transport

## Scope

This milestone removes the per-beat SST `StandardMem -> MemEvent ->
MemController -> MemBackendConvertor` object path from the optimized execution
mode. It does **not** replace DRAMSim3 with a latency formula and does not
change the modeled accelerator.

The optional `direct_dramsim3_transport` mode retains:

- one independent DRAMSim3 `MemorySystem` for every bound HBM pseudo-channel;
- the frozen HBM2 INI, address stream, read/write operation, and request order;
- the 1 ns request link, 1 GHz memory clock, and 1 ns response link;
- DRAMSim3 `WillAcceptTransaction`, command queues, bank timing, callbacks,
  row-buffer state, refresh, statistics, and energy accounting;
- the existing finite AXI outstanding limit, response queue, registered
  per-channel arbiter, FIFO backpressure, and evaluate/commit scheduler; and
- the same payload completion and request/byte/activity ledgers.

SST executes clocks at priority 40 and link events at priority 50. Therefore a
request link event exactly on a memory-clock edge is issued on the following
edge, and a response link event exactly on a core edge is visible on the next
core tick. The direct transport encodes both boundaries explicitly. Idle HBM
channels are advanced lazily with the already validated exact DRAMSim3
`AdvanceIdle` implementation before statistics are emitted.

The legacy `sst_memHierarchy_dramsim3` mode remains the default and is the
equivalence oracle. Result JSON records the selected backend explicitly, so
the sole approved result-field difference is the `backend` provenance string.

## Controlled result

Frozen run: `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`.

| System | Frozen baseline host s | Direct transport host s | Cumulative speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 7.884 | 2.790 | 2.826x | 4,778,979 |
| GraSU+ReGraph | 105.218 | 28.327 | 3.714x | 15,310,428 |

The two-system geometric-mean cumulative speedup is **3.240x**. Relative to
the preceding persistent-initiator milestone, this transport improves host
time by 1.291x for Spine and 1.640x for GraSU+ReGraph, or **1.455x** by
geometric mean.

The candidate SST plugin SHA-256 is
`5149ff788ff93d53080afb99304f785313b48f89e151ae96f42beba89def02ad`.
The linked patched DRAMSim3 library SHA-256 is
`3831d532874c688dadca64f8fed988295943fff500ff7ec6c48fb00f0d3adb94`;
the HBM INI SHA-256 is
`d1e865c6528acbc41f0768667063702bfb4033f24bcd46119ad25bfc5ad4fb5f`.

## Equivalence evidence

The fail-closed comparator reports PASS:

- all 354 architectural fields are identical across the two system results;
- the two `backend` fields make the explicit, approved provenance transition;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, correctness, request ordering/locality, stalls, DRAM commands, row
  hits, activity, and energy counters are unchanged.

Four transport microbenchmarks independently cover sequential reads,
cross-row reads, 50/50 mixed reads and writes, and payload round trips. Their
cycles and DRAM JSON files are exact; only the backend provenance differs.

Committed compact evidence is under
`docs/evidence/simulator_throughput_candidate24_direct_transport_20260728`.
Raw evidence remains outside Git:

- matrix: `/data/tmp/chuxiao/simulator_throughput_candidate24_direct_transport_provenance_20260728`;
- equivalence: `/data/tmp/chuxiao/simulator_throughput_candidate24_direct_transport_provenance_20260728_equivalence`;
- memory microbenchmarks: `/data/tmp/chuxiao/direct_dramsim3_micro_candidate24_20260728`; and
- payload microbenchmark: `/data/tmp/chuxiao/direct_dramsim3_payload_candidate24_20260728`.

This remains one frozen synthetic probe. It does not satisfy the final 10x
medium/large geometric-mean gate and does not replace the real-dataset or R19
matrix.

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
  --out-dir /data/tmp/chuxiao/direct_transport_reproduction \
  --jobs 1 --timeout-seconds 600 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_candidate19_dense_initiator_state_20260728 \
  --candidate-dir /data/tmp/chuxiao/direct_transport_reproduction \
  --out-dir /data/tmp/chuxiao/direct_transport_reproduction_equivalence \
  --allow-direct-transport
```

Validation at this milestone: 586 Python tests passed with 5 expected skips;
the 104-test shared-core and 29-test GraSU C++ suites passed; and
`git diff --check` was clean.
