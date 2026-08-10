# Simulator throughput milestone 3: AXI admission hot path

## Scope

This milestone removes host-only work from the shared AXI and registered HBM
arbitration path. It does not change an architecture profile, clock, FIFO
depth, AXI width, outstanding limit, request, response, arbitration winner, or
DRAM command.

The implementation changes are:

- separate backend admission headers from complete requests, so a blocked AXI
  write does not construct or copy a payload that the backend cannot accept;
- store registered-arbiter intent and grant state as per-initiator channel
  bitmasks and visit only active channels while preserving numeric
  round-robin selection;
- cache whether an AXI master owns internal work, replacing two scheduler-guard
  scans of ten containers per active cycle with one bit test; and
- retain the request FIFO check independently, so a newly committed request
  wakes an otherwise idle AXI master on the same simulated schedule as before.

An attempted fixed-channel bulk rejection counter was measured separately and
removed. It did not improve the workload because contention consists of
several AXI masters making one attempt each, not one master making many
equivalent attempts in a cycle.

## Controlled A/B result

The cumulative candidate was compared with the frozen pre-optimization
baseline on the same Candidate10 residual PageRank probe and exact-idle
SST/DRAMSim3 stack.

| System | Baseline host s | Candidate host s | Host speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 7.884 | 6.207 | 1.270x | 4,778,979 |
| GraSU+ReGraph | 105.218 | 75.989 | 1.385x | 15,310,428 |

The two-system geometric-mean speedup is 1.326x. This is a cumulative
throughput result relative to the frozen baseline, not the final medium/large
suite result and not evidence for the 10x target by itself.

## Exactness evidence

`scripts/analyze_exact_idle_equivalence.py` reports PASS:

- all 356 pre-existing result fields are identical;
- both complete result JSON files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- no observability field was added or removed.

Committed evidence is under
`docs/evidence/simulator_throughput_candidate10_axi_hotpath_20260728`. Raw runs
remain outside Git:

- candidate: `/data/tmp/chuxiao/simulator_throughput_candidate10_axi_pending_cache_20260728`
- equivalence: `/data/tmp/chuxiao/simulator_throughput_candidate10_axi_pending_cache_equivalence_20260728`

The candidate SST plugin SHA-256 is
`a6582c443750a9fe4bffefc6bf9695954cca7261b1b698cd8d3d2854a40d3f45`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-script-repro-v1/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-script-repro-v1-install
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst

make -C cpp/sst -j8
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate10_axi_reproduction \
  --jobs 1 --timeout-seconds 600 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_baseline_spread_residual_20260728 \
  --candidate-dir /data/tmp/chuxiao/simulator_throughput_candidate10_axi_reproduction \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate10_axi_reproduction_equivalence
```

Validation at this milestone: 585 Python tests passed with 5 expected skips;
the 102-test shared-core and 29-test GraSU C++ suites passed;
`git diff --check` was clean.
