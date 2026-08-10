# Simulator throughput milestone 9: release LTO build

## Scope

The SST element previously used `-O2 -g` even for formal experiment runs.
This milestone changes its default host build to `-O3 -DNDEBUG -flto`. The
setting is isolated in `SPINE_HOST_OPT_FLAGS`, so profiling and debugging can
override it without editing the Makefile:

```bash
make -C cpp/sst SPINE_HOST_OPT_FLAGS='-O2 -g'
```

This is a host-execution optimization only. Simulator source, architecture
configuration, request sequence, evaluate-then-commit behavior, SST model,
DRAMSim3 model, and reported clock remain unchanged.

## Controlled result

| System | Frozen baseline host s | Release-LTO host s | Cumulative speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 7.884 | 3.682 | 2.141x | 4,778,979 |
| GraSU+ReGraph | 105.218 | 47.790 | 2.202x | 15,310,428 |

The two-system geometric-mean cumulative speedup is **2.173x**. Relative to
the preceding stable-response milestone, the release build improves host time
by about 1.072x for Spine and 1.031x for GraSU+ReGraph, or 1.051x by geometric
mean.

The formal build at `build/sst/libspine_cycle.so` and the isolated experiment
build at `build/sst-release-experiment/libspine_cycle.so` have the same
SHA-256:

`a38ab7877ea75992574cf62c12bffe817e756f1406131c3fec14701641d98220`.

## Exactness evidence

The frozen exact-idle comparator reports PASS:

- all 356 pre-existing result fields are identical;
- both complete result JSON files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- no observability field was added or removed.

Committed evidence is under
`docs/evidence/simulator_throughput_candidate17_release_lto_20260728`.
Raw files remain outside Git:

- candidate: `/data/tmp/chuxiao/simulator_throughput_candidate17_release_lto_20260728`
- equivalence: `/data/tmp/chuxiao/simulator_throughput_candidate17_release_lto_20260728_equivalence`

This is still one frozen probe. It does not satisfy the final 10x medium/large
geometric-mean gate or replace the real-dataset and R19 matrix.

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
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate17_reproduction \
  --jobs 1 --timeout-seconds 600 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_baseline_spread_residual_20260728 \
  --candidate-dir /data/tmp/chuxiao/simulator_throughput_candidate17_reproduction \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate17_reproduction_equivalence
```

The source-equivalent milestone-8 regression remains green: 585 Python tests
passed with 5 expected skips; the 104-test shared-core and 29-test GraSU C++
suites passed; and `git diff --check` was clean.
