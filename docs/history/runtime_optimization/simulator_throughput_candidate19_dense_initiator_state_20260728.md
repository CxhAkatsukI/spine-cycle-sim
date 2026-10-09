# Simulator throughput milestone 10: persistent initiator state

## Scope

This milestone removes hash-node churn from the shared memory hot path without
changing memory arbitration or queue behavior.

- Registered initiator membership is now a direct byte-vector lookup. The
  simulator's fixed architecture IDs are sparse but bounded, so this replaces
  a hash lookup on every attempted backend request with one bounds check and
  one indexed load.
- The SST backend keeps one persistent state object for each registered
  initiator. Response queues, one-cycle retired response views, staged pops,
  staged submissions, and outstanding counts no longer allocate and destroy
  `unordered_map` nodes each active cycle.
- Small active-ID vectors identify only the initiators that require reset or
  commit work in the current cycle. Per-initiator response order and the
  registered per-channel arbiter are unchanged.
- `grasu_regraph.cpp` now includes `<unordered_set>` directly instead of
  depending on an unrelated transitive include.

## Controlled result

| System | Frozen baseline host s | Candidate host s | Cumulative speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 7.884 | 3.602 | 2.189x | 4,778,979 |
| GraSU+ReGraph | 105.218 | 46.449 | 2.265x | 15,310,428 |

The two-system geometric-mean cumulative speedup is **2.227x**. Relative to
the preceding release-LTO milestone, this change improves host time by about
1.022x for Spine and 1.029x for GraSU+ReGraph, or 1.025x by geometric mean.

The candidate SST plugin SHA-256 is
`88b2d17841068cc4dab3bd0b0d23aafbc950722e8c0f3d8f10c2a5db1a5dfa20`.

## Exactness evidence

The frozen exact-idle comparator reports PASS:

- all 356 pre-existing result fields are identical;
- both complete result JSON files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- no observability field was added or removed.

Committed evidence is under
`docs/evidence/simulator_throughput_candidate19_dense_initiator_state_20260728`.
Raw files remain outside Git:

- candidate: `/data/tmp/chuxiao/simulator_throughput_candidate19_dense_initiator_state_20260728`
- equivalence: `/data/tmp/chuxiao/simulator_throughput_candidate19_dense_initiator_state_20260728_equivalence`

This remains one frozen probe and does not satisfy the final 10x medium/large
geometric-mean gate or replace the real-dataset and R19 matrix.

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
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate19_reproduction \
  --jobs 1 --timeout-seconds 600 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_baseline_spread_residual_20260728 \
  --candidate-dir /data/tmp/chuxiao/simulator_throughput_candidate19_reproduction \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate19_reproduction_equivalence
```

Validation at this milestone: 585 Python tests passed with 5 expected skips;
the 104-test shared-core and 29-test GraSU C++ suites passed; and
`git diff --check` was clean.
