# Simulator progress observability

## Purpose

Publication-scale runs need observable forward progress without changing the
modeled architecture. Candidate 84 adds an optional atomic JSON snapshot from
the SST component. The snapshot reports the current phase, simulated cycles,
algorithm iteration, accepted memory requests, outstanding memory requests,
and host timestamp. The campaign monitor also shows the cycle and request
counters.

The feature is disabled when `SPINE_CAMPAIGN_PROGRESS_PATH` is empty. It does
not skip cycles, change event order, resize queues, or alter any architectural
parameter. The campaign runner sets a private path for each job.

## Exactness evidence

The frozen `syn_spread_e512__residual_pagerank` pair was run with the Candidate
81 plugin and the Candidate 84 native+PGO plugin using the direct DRAMSim3
backend. Both complete result files are byte-identical:

| System | Candidate 81 cycles | Candidate 84 cycles | Result identity |
|---|---:|---:|---|
| Spine | 4,778,979 | 4,778,979 | byte-identical |
| GraSU+ReGraph | 15,310,428 | 15,310,428 | byte-identical |

All 26 per-channel DRAMSim3 JSON and epoch JSON files are also byte-identical.
The final snapshot reports 9,751,632 accepted requests and zero outstanding
requests. Machine-readable hashes are in
`docs/evidence/simulator_progress_candidate84_20260729/equivalence.json`.

## Build and training

The PGO generation and use builds must share the same build and profile paths.
The training case executes both architecture models.

```bash
cd /home/chuxiao/spine-cycle-sim-publication
export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate59-cleanpatch-reproduction-backend-20260729/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate59-cleanpatch-reproduction-install-20260729
export BUILD=/data/tmp/chuxiao/candidate84-progress-native-pgo-build-20260729
export PGO=/data/tmp/chuxiao/candidate84-progress-native-pgo-data-20260729

make -C cpp/sst pgo-native-generate -j8 \
  BUILD_DIR="$BUILD" PGO_PROFILE_DIR="$PGO"

SPINE_CYCLE_ELEMENT_DIR="$BUILD" \
SPINE_SST_MEMORY_BACKEND=direct_dramsim3_transport \
GRASU_SST_MEMORY_BACKEND=direct_dramsim3_transport \
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/candidate84-progress-native-pgo-training-20260729 \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir "$BUILD" --no-build

make -C cpp/sst pgo-native-use -j8 \
  BUILD_DIR="$BUILD" PGO_PROFILE_DIR="$PGO"
```

The formal plugin SHA-256 is
`5d9d879e0c70c72bb8eae979ec11177c97ddd6373e838836e460f337a1461431`.
