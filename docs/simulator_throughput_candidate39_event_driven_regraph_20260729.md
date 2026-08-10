# Simulator throughput milestone 14: exact event-driven ReGraph pipeline

## Scope

This milestone adds transition notifications to the registered FIFO model and
uses them to suspend deterministic ReGraph wait states. A producer can now be
woken when a full FIFO becomes nonfull, while a consumer can be woken when an
empty FIFO becomes nonempty. ReGraph readers also publish an exact done edge.

The gather and merger bulk-account every omitted full-FIFO stall cycle. Apply
and HBM-wrapper components suspend only when no local state can advance and no
architectural stall counter would change. Reset, drain, merge work, timed
pipeline delays, finite-window stalls, and all contended states still execute
at their original cycle granularity. Staged evaluate state is explicitly
cleared on commit so sleeping components cannot replay a transaction.

## Controlled result

Frozen run: `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`, using the normal
`-O3 -DNDEBUG -flto` build and direct DRAMSim3 transport.

| System | Candidate 24 host s | Candidate 39 host s | Speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 2.790 | 2.708 | 1.030x | 4,778,979 |
| GraSU+ReGraph | 28.327 | 27.393 | 1.034x | 15,310,428 |

The controlled two-system geometric-mean speedup is **1.032x**. Relative to
the original frozen binary, the current normal build is 2.911x faster for
Spine, 3.841x faster for GraSU+ReGraph, and 3.344x faster in geometric mean.
PGO remains an orthogonal build optimization and must be retrained after this
source change.

The component sample period was 1,000 cycles. Compared with Candidate 33,
gather evaluate samples fell from 14,435 to 3,945 (72.7%), HBM-wrapper samples
from 15,310 to 7,409 (51.6%), and apply samples from 15,304 to 14,426 (5.7%).
Merger still consumes one real row per active cycle and therefore remains near
14,362 samples. This identifies the next target as AXI/DRAM execution and
deterministic multi-cycle work batching, not additional empty-FIFO checks.

## Exactness gate

The fail-closed comparator against Candidate 24 reports PASS:

- all 356 pre-existing result fields are identical;
- both complete `result.json` files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, correctness, requests, bytes, traces, stalls, DRAM commands,
  activity, and energy counters are unchanged.

The candidate plugin SHA-256 is
`bc53d8ddd231430b92a3997ede84f26a4b0a440c374a39e56a540711c3d7ba6c`.
Compact evidence is committed under
`docs/evidence/simulator_throughput_candidate39_event_driven_regraph_20260729`.
Raw evidence remains under `/data/tmp/chuxiao/`:

- candidate: `simulator_throughput_candidate39_apply_window_wakeup_20260729`;
- equivalence:
  `simulator_throughput_candidate39_apply_window_wakeup_20260729_equivalence`;
  and
- component profile: `simulator_throughput_candidate39_profile_20260729`.

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
  --out-dir /data/tmp/chuxiao/candidate39-reproduction \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_candidate24_direct_transport_provenance_20260728 \
  --candidate-dir /data/tmp/chuxiao/candidate39-reproduction \
  --out-dir /data/tmp/chuxiao/candidate39-reproduction-equivalence \
  --allow-direct-transport
```

Validation: 105 shared-core tests, 29 GraSU tests, and 586 Python tests pass;
five Python tests are expected skips. `git diff --check` is clean.

## Next step

This milestone is infrastructure, not the 10x acceptance result. The frozen
profile remains dominated by the degree AXI master, direct DRAMSim3 clocking,
apply-window work, the row-by-row merger, and controller busy-cycle polling.
The next milestone must reduce those calls while preserving the same strict
equivalence gate.
