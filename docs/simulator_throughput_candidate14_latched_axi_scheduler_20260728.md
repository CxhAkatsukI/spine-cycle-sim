# Simulator throughput milestone 7: latched AXI scheduling

## Scope

This milestone removes per-cycle polling of sleeping AXI masters without
changing the global evaluate-then-commit protocol. It preserves component
registration order, clock-domain filtering, AXI round-robin progression,
FIFO visibility, and all existing counters and traces.

The scheduler now supports a latched evaluate bitmap in addition to its
existing latched commit bitmap. AXI masters use it as follows:

- an AXI master remains evaluate-ready while it owns internal parent, burst,
  response, write-ingress, or backend-mapping state;
- its SPSC request FIFO notifies it only when a staged push becomes visible in
  FIFO commit, so a cycle-N push still cannot be consumed before cycle N+1;
- each selected AXI evaluate arms exactly one commit for the same cycle,
  preserving the baseline's per-cycle round-robin update even when no other
  state changes; and
- components without a latched contract retain the original dynamic readiness
  call. Stable readiness tokens are also available as a lower-overhead fallback
  for dynamic components.

Selected evaluate and commit bits are consumed in increasing component-slot
order. No component is parallelized, reordered, or advanced across a clock
edge.

## Controlled result

The frozen Candidate10 residual PageRank probe used the fresh Candidate13
SST/DRAMSim3 backend and a rebuilt simulator element.

| System | Frozen baseline host s | Candidate host s | Cumulative speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 7.884 | 4.134 | 1.907x | 4,778,979 |
| GraSU+ReGraph | 105.218 | 49.652 | 2.119x | 15,310,428 |

The two-system geometric-mean cumulative speedup is **2.010x**. Relative to
the preceding fresh Candidate13 run, this milestone is 1.115x faster for Spine
and 1.077x faster for GraSU+ReGraph, or 1.096x by geometric mean. The shared
core C++ regression wall time also fell from about 4.85 seconds before the AXI
hot-path work to about 3.4 seconds, but test-suite wall time is supporting
evidence rather than a formal performance claim.

This is still one frozen probe. It does not satisfy the final 10x medium/large
geometric-mean gate or replace the real-dataset and R19 matrix.

## Exactness evidence

`scripts/analyze_exact_idle_equivalence.py` reports PASS:

- all 356 pre-existing result fields are identical;
- both complete result JSON files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- no observability field was added or removed.

The core regression adds a 130-component latched-evaluate test that crosses
three bitmap words. It checks one-shot wakeup behavior, registration-order
dispatch, exact cycle labels, and notifier rebinding after component removal.

Committed evidence is under
`docs/evidence/simulator_throughput_candidate14_latched_axi_scheduler_20260728`.
Raw files remain outside Git:

- candidate: `/data/tmp/chuxiao/simulator_throughput_candidate15_latched_axi_scheduler_20260728`
- equivalence: `/data/tmp/chuxiao/simulator_throughput_candidate15_latched_axi_scheduler_20260728_equivalence`

The candidate SST plugin SHA-256 is
`7555161f7599f5b00634cb473571d39a847dc6a743a78a9197b469aa549620bc`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate13-reproduction-build-20260728/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate13-reproduction-install-20260728
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst

make -C cpp/sst -j8
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate14_reproduction \
  --jobs 1 --timeout-seconds 600 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_baseline_spread_residual_20260728 \
  --candidate-dir /data/tmp/chuxiao/simulator_throughput_candidate14_reproduction \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate14_reproduction_equivalence
```

Validation at this milestone: 585 Python tests passed with 5 expected skips;
the 103-test shared-core and 29-test GraSU C++ suites passed; and
`git diff --check` was clean.
