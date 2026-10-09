# Simulator throughput milestone 8: stable backend response views

## Scope

This milestone removes a redundant `BackendResponse` and payload copy between
the shared memory backend and each AXI master. It does not change request
generation, response ordering, FIFO timing, AXI limits, DRAM timing, counters,
or traces.

During evaluate, an AXI master now validates the backend's immutable response
queue and stages only the number of responses it can consume. During commit it
reads those responses through `MemoryBackend::staged_response_at()`. If the
backend commits first, it moves the popped objects into a one-cycle retired
view; if AXI commits first, it reads the original queue. The response payload
therefore has a stable lifetime in either component registration order without
an allocation or byte-vector copy.

The core regression runs the same 1,600-byte cross-page read with both
backend-before-AXI and AXI-before-backend registration. It requires identical
cycles, payload, AXI counters, and backend request counts.

## Controlled result

The frozen Candidate10 residual PageRank probe used the fresh Candidate13
SST/DRAMSim3 backend and a rebuilt simulator element.

| System | Frozen baseline host s | Candidate host s | Cumulative speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 7.884 | 3.947 | 1.998x | 4,778,979 |
| GraSU+ReGraph | 105.218 | 49.250 | 2.136x | 15,310,428 |

The two-system geometric-mean cumulative speedup is **2.066x**. Relative to
the preceding latched-AXI milestone, this change is about 1.047x faster for
Spine and 1.008x faster for GraSU+ReGraph, or 1.027x by geometric mean. The
gain is modest, so this is a retained low-risk cleanup rather than evidence
that the final throughput target has been reached.

This remains one frozen probe. It does not satisfy the final 10x medium/large
geometric-mean gate or replace the real-dataset and R19 matrix.

## Exactness evidence

`scripts/analyze_exact_idle_equivalence.py` reports PASS:

- all 356 pre-existing result fields are identical;
- both complete result JSON files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- no observability field was added or removed.

Committed evidence is under
`docs/evidence/simulator_throughput_candidate16_stable_response_view_20260728`.
Raw files remain outside Git:

- candidate: `/data/tmp/chuxiao/simulator_throughput_candidate16_stable_response_view_20260728`
- equivalence: `/data/tmp/chuxiao/simulator_throughput_candidate16_stable_response_view_20260728_equivalence`

The candidate SST plugin SHA-256 is
`ed7be1eabe62762deaf6aa93e697cdd18b3b05ce0dddaaafbe3358f5ed3902a2`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate13-reproduction-build-20260728/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate13-reproduction-install-20260728
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst

cmake --build build/cycle-core -j8
ctest --test-dir build/cycle-core --output-on-failure
make -C cpp/sst -j8
python3 -m unittest discover -s tests

python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate16_reproduction \
  --jobs 1 --timeout-seconds 600 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_baseline_spread_residual_20260728 \
  --candidate-dir /data/tmp/chuxiao/simulator_throughput_candidate16_reproduction \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate16_reproduction_equivalence
```

Validation at this milestone: 585 Python tests passed with 5 expected skips;
the 104-test shared-core and 29-test GraSU C++ suites passed; and
`git diff --check` was clean.
