# Simulator throughput milestone 5: DRAM statistics hot path

## Scope

This milestone removes host-only work from the exact-idle DRAMSim3 backend. It
does not change a DRAM timing parameter, request, command, bank transition,
arbitration decision, completion cycle, power counter, or output statistic.

`patches/dramsim3_stats_hotpath.patch` makes three behavior-preserving changes:

- fixed, hot statistics use enum-indexed pointers bound once after statistic
  initialization instead of constructing and hashing a string on every update;
- `ChannelState` maintains the exact number of open banks per rank, making the
  per-cycle all-bank-idle query O(1); and
- timing propagation helpers return immediately when their timing list is
  empty, avoiding loops that provably have no state effect.

The generic string-based statistics API remains available for non-hot and
externally named statistics. The isolated backend build applies this patch
after the exact-idle and active-command-queue patches and records all hashes.

## Controlled A/B result

The cumulative candidate was compared with the frozen pre-optimization
baseline on the Candidate10 residual PageRank probe.

| System | Baseline host s | Candidate host s | Host speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 7.884 | 4.973 | 1.585x | 4,778,979 |
| GraSU+ReGraph | 105.218 | 61.316 | 1.716x | 15,310,428 |

The cumulative two-system geometric-mean speedup is **1.649x**. Relative to
the preceding active-command-queue milestone, this change improves Spine by
1.121x and GraSU+ReGraph by 1.124x on the controlled run. This remains below
the frozen 10x medium/large-suite target, so it is an intermediate milestone,
not the final performance claim.

## Exactness evidence

`scripts/analyze_exact_idle_equivalence.py` reports PASS:

- all 356 pre-existing result fields are identical;
- both complete result JSON files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- no observability field was added or removed.

Committed evidence is under
`docs/evidence/simulator_throughput_candidate12_dramsim3_stats_hotpath_20260728`.
Raw runs remain outside Git:

- candidate: `/data/tmp/chuxiao/simulator_throughput_candidate12_dramsim3_stats_hotpath_20260728`
- equivalence: `/data/tmp/chuxiao/simulator_throughput_candidate12_dramsim3_stats_hotpath_equivalence_20260728`
- experimental DRAMSim3 source/build: `/data/tmp/chuxiao/candidate12-dramsim3-stats-hotpath-full-20260728`

The experimental `libdramsim3.so` SHA-256 is
`d1205f636685d56321e8fed45adc36aef8536770556b8cba55dbf756876de4bc`.

The reproduction command below was also run from an empty work directory. Its
fresh library completed Spine in 4.99 s and GraSU+ReGraph in 62.65 s, retained
the same two cycle counts, and again matched all results and 26 DRAM JSON files
byte-for-byte. Its cumulative geometric-mean speedup was 1.629x. The fresh
build manifest and equivalence rows are committed beside the controlled A/B
evidence.

## Reproduction

Build a new isolated SST/DRAMSim3 stack with all exact hot-path patches:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/build_exact_idle_dramsim3_backend.py \
  --work-root /data/tmp/chuxiao/candidate12-reproduction \
  --install-prefix /data/tmp/chuxiao/candidate12-reproduction-install \
  --jobs 8
```

Then run the frozen comparison:

```bash
export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate12-reproduction/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate12-reproduction-install
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst

python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/candidate12-reproduction-run \
  --jobs 1 --timeout-seconds 600 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build
```

The build script runs the standalone DRAMSim3 idle-advance A/B harness and
requires byte-identical final and epoch statistics before installing the SST
element. Full repository regression and a fresh-build smoke run are recorded
with the commit that introduces this milestone.
