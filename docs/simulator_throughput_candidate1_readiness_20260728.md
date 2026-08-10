# Simulator throughput milestone 1: idle component readiness

## Change

This milestone removes host calls to completed or blocked GraSU update-path
components while preserving the simulated hardware schedule. Dynamic readiness
guards were added to direct search, dispatch, PMA processors, and the degree
updater. The PMA processor also maintains an O(1) outstanding-work count instead
of scanning every lane when the controller tests for quiescence.

The guards only suppress an `evaluate()` call when the component cannot observe
an input, AXI response, issuable lane state, or pending operation in that cycle.
Every staged mutation is consumed and cleared in `commit()` so a skipped
evaluation cannot replay stale state.

## Controlled A/B result

The frozen residual PageRank probe was rerun with the same workload, normalized
K=1 profiles, exact-idle SST/DRAMSim3 backend, HBM configuration, and 4,096-cycle
component profiler period.

| System | Baseline host s | Candidate host s | Host speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 7.884 | 7.748 | 1.018x | 4,778,979 |
| GraSU+ReGraph | 105.218 | 94.551 | 1.113x | 15,310,428 |

This is a narrow first optimization, not the final throughput result. Its main
value is proving the exact readiness mechanism. The scheduler profile previously
sampled each of `grasu-processor0..3`, `grasu-dispatch`, and
`grasu-degree-updater` in all 3,738 residual-compute sample intervals. Those
completed update components have zero sampled calls in the candidate run.

## Equivalence gate

`scripts/analyze_exact_idle_equivalence.py` reports PASS:

- all 356 pre-existing result fields are identical;
- both complete result JSON files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical;
- no observability field was added or removed.

The committed machine-readable evidence is under
`docs/evidence/simulator_throughput_candidate1_readiness_20260728`. Raw run
directories are deliberately kept outside Git:

- baseline: `/data/tmp/chuxiao/simulator_throughput_baseline_spread_residual_20260728`
- candidate: `/data/tmp/chuxiao/simulator_throughput_candidate1_spread_residual_20260728`
- equivalence: `/data/tmp/chuxiao/simulator_throughput_candidate1_equivalence_20260728`

The candidate SST plugin SHA-256 was
`2f149d03dba1b2d08b715b9a364ce22af3181a96ffe7fd24aa930aa1fe1b70c6`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-script-repro-v1/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-script-repro-v1-install
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst
export SPINE_SIM_PROFILE_COMPONENT_PERIOD=4096
export SPINE_SIM_PROFILE_COMPONENT_REPORT=1

make -C cpp/sst -j8
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate1_reproduction \
  --jobs 1 --timeout-seconds 600 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_baseline_spread_residual_20260728 \
  --candidate-dir /data/tmp/chuxiao/simulator_throughput_candidate1_reproduction \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate1_reproduction_equivalence
```

Validation at this milestone: 585 Python tests passed with 5 expected skips;
both C++ test executables passed; `git diff --check` was clean.
