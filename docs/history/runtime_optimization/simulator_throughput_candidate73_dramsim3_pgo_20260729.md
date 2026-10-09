# Simulator throughput milestone 22: DRAMSim3 profile-guided build

## Scope

The simulator element already used two-system profile-guided optimization, but
the DRAMSim3 shared library still used only native LTO. This milestone trains
the patched DRAMSim3 implementation with the same frozen Spine and normalized
GraSU+ReGraph pair, then rebuilds it with GCC profile feedback, native code
generation, LTO, and semantic interposition disabled.

This is a host implementation optimization. It does not change the HBM
configuration, DRAM timing, request stream, command policy, architecture
profile, modeled clock, FIFO/AXI behavior, or accelerator cycle count.

## Controlled result

The frozen workload is `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`. Candidate 73
uses the accepted Candidate 67 native+PGO simulator element and only replaces
the linked DRAMSim3 library.

| System | Candidate 67 median host s | Candidate 73 median host s | Incremental speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 1.856 | 1.728 | 1.074x | 4,778,979 |
| GraSU+ReGraph | 20.305 | 19.182 | 1.059x | 15,310,428 |

The incremental two-system geometric-mean speedup is **1.066x**. Relative to
the original frozen binary, Candidate 73 is **4.563x** faster for Spine,
**5.485x** faster for GraSU+ReGraph, and **5.003x** faster in geometric mean.
The 10x objective remains open.

## Exactness gate

All three repetitions pass the fail-closed Candidate 24 comparator:

- both complete architecture result files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, correctness, requests, bytes, locality, FIFO/AXI stalls, DRAM
  commands, activity, and energy counters are unchanged.

The optimized DRAMSim3 SHA-256 is
`9db26860cde335dd62c9e013d444b67ec98e8772107b39e15eb15a0ffdb8d906`.
Compact evidence is under
`docs/evidence/simulator_throughput_candidate73_dramsim3_pgo_20260729`.

## Reproduction

Start from a patched backend produced by
`scripts/build_exact_idle_dramsim3_backend.py`. The generate and use steps
must reuse the same source and build directory because GCC profile filenames
encode the object path.

```bash
cd /home/chuxiao/spine-cycle-sim-publication

python3 scripts/rebuild_dramsim3_pgo.py \
  --source /data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729 \
  --build-dir /data/tmp/chuxiao/candidate73-dramsim3-pgo-generate-build-20260729 \
  --profile-dir /data/tmp/chuxiao/candidate73-dramsim3-pgo-data-20260729 \
  --mode generate --jobs 8

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate59-cleanpatch-reproduction-install-20260729
export SPINE_CYCLE_ELEMENT_DIR=/data/tmp/chuxiao/candidate67-native-pgo-build-20260729
export SPINE_SST_MEMORY_BACKEND=direct_dramsim3_transport
export GRASU_SST_MEMORY_BACKEND=direct_dramsim3_transport

python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/candidate73-dramsim3-pgo-training-20260729 \
  --jobs 1 --timeout-seconds 1200 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir "$SPINE_CYCLE_ELEMENT_DIR" --no-build

python3 scripts/rebuild_dramsim3_pgo.py \
  --source "$SPINE_IDLE_DRAMSIM3_SRC" \
  --build-dir /data/tmp/chuxiao/candidate73-dramsim3-pgo-generate-build-20260729 \
  --profile-dir /data/tmp/chuxiao/candidate73-dramsim3-pgo-data-20260729 \
  --mode use --jobs 8
```

Run the frozen pair three times and compare each output with Candidate 24 using
`scripts/analyze_exact_idle_equivalence.py --allow-direct-transport`.

## Next step

Compiler feedback has now been applied to both the simulator core and DRAMSim3.
Further material gains require reducing exact per-cycle and per-request host
bookkeeping in the scheduler, AXI response path, and GraSU+ReGraph degree/apply
path, or proving larger exact event windows. PGO alone cannot meet the 10x
target.
