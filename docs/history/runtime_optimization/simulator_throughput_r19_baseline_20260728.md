# Simulator throughput R19 baseline

## Scope

This milestone freezes the host-runtime optimization boundary before changing
the simulator implementation. The simulated Spine and conversion-free
GraSU+ReGraph architectures, algorithm contracts, FIFO/AXI/HBM behavior, and
DRAMSim3 backend remain immutable. Only host execution time, host throughput,
peak RSS, and profiler observations may change.

The machine-readable contract is
`configs/contracts/simulator_throughput_r19_v1.json`. It fixes the baseline
source revision, SST plugin, exact-idle patches, HBM profile, workload coverage,
equivalence fields, resource limits, and acceptance thresholds.

## Fresh baseline probe

The first fresh probe uses the same residual PageRank workload on both frozen
K=1 architectures. It was run sequentially on the same host with the exact-idle
SST/DRAMSim3 backend and a 4,096-cycle component-profile sampling period.

| System | Simulated cycles | HBM requests | Host seconds | Cycles/host second |
|---|---:|---:|---:|---:|
| Spine | 4,778,979 | 410,621 | 7.884 | 606,144 |
| GraSU+ReGraph | 15,310,428 | 9,751,632 | 105.218 | 145,512 |

Every architecture and mathematical oracle passed. The result and all DRAM
JSON hashes are pinned in
`docs/evidence/simulator_throughput_r19_baseline_20260728/baseline_rows.csv`.
Raw files remain under
`/data/tmp/chuxiao/simulator_throughput_baseline_spread_residual_20260728` and
are not committed.

The sampled component work extrapolates to a material fraction of both runs.
The leading sampled components are `sst-hbm-backend` for Spine and
`grasu-regraph-p0-degree` for GraSU+ReGraph. This is a profiling observation,
not yet a causal speedup claim. The next milestone must use controlled A/B runs
before accepting an optimization.

## Coverage and acceptance

The optimization evidence must cover AU, SU, WK, SO, and BC, retain Amazon,
Web-Google, and Soc-Flickr as holdouts, and use R19-32 as the scale endpoint.
No selected dataset may be silently omitted. A run that reaches a fixed time or
memory limit is reported as a timeout rather than extrapolated as a result.

The hard host-runtime target is a 10x geometric-mean speedup on non-tiny
medium/large workloads, with no case regressing by more than 5%. R19-32 SSSP
and CC have a 30-minute per-system limit; Full and residual PageRank have a
60-minute limit. A 100x speedup remains a stretch target for Python- or
scheduler-dominated cases.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-script-repro-v1/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-script-repro-v1-install
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst
export SPINE_SIM_PROFILE_COMPONENT_PERIOD=4096
export SPINE_SIM_PROFILE_COMPONENT_REPORT=1

python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/simulator_throughput_baseline_reproduction \
  --jobs 1 --timeout-seconds 600 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build
```

Host wall time is expected to vary with machine load. Architectural JSON and
DRAM statistics must not vary.
