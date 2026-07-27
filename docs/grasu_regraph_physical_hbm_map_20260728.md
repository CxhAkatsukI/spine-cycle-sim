# GraSU + ReGraph Physical HBM Address Contract

## Purpose

The Candidate10 K1/K2/K4 profiles previously inherited logical addresses whose
4 GiB partition stride was a multiple of the 512 MiB HBM pseudo-channel
capacity. `SstMemoryBackend` maps each request to the selected pseudo-channel as
`address % channel_capacity_bytes`; consequently, all destination partitions
had identical DRAM timing addresses even though the payload shadow retained
distinct 64-bit logical addresses. Functional oracles could pass while row
locality, contention, latency, and HBM energy were not physically meaningful.

This change freezes a non-aliasing physical map for the normalized comparator.
It does not change GraSU/ReGraph modules, pipeline counts, FIFO depths,
outstanding limits, clock, update semantics, or algorithm semantics.

## Frozen map

All offsets are local to one 512 MiB HBM pseudo-channel.

| Region | Base | Reserved extent |
|---|---:|---:|
| Update records | 0 MiB | actual striped batch payload |
| Binary heads | 64 MiB | 4 x 16 MiB partition windows |
| Row offsets | 128 MiB | 4 x 16 MiB partition windows |
| PMA segments | 256 MiB | 4 x 16 MiB partition windows |
| ReGraph source state | 384 MiB | two 1 MiB ping-pong buffers |
| ReGraph vertex state | 0 MiB on channel 30 | actual vertex array |
| PageRank degree | 16 MiB on channel 30 | actual degree array |

The profile therefore supports at most four 65,536-destination partitions
(262,144 compact vertices) without a new address map. Runs requiring a fifth
partition fail before SST starts.

## Runtime gates

`spine_cycle_sim/experiments/grasu_addressing.py` performs four checks for every
K1/K2/K4 v4 run:

1. Reconstruct full-word PMA reservations after the host vertex permutation.
2. Check each partition's row, binary-head, and PMA footprint against 16 MiB.
3. Check every actual buffer extent against the 512 MiB channel capacity.
4. Reject overlapping windows whenever two buffers use a common pseudo-channel.

The three HLS-derived runners inject every validated base and stride into SST;
they also record `physical_hbm_address_regions` in each run manifest. The
capability catalog, profile hashes, feasibility contract, and shared comparison
manifest are regenerated together by:

```bash
python3 scripts/freeze_grasu_regraph_k_pipeline.py
```

## Validation

The corrected K1 profiles passed execution-driven SST/DRAMSim3 smoke tests:

| Algorithm | Cycles | Backend requests | Result |
|---|---:|---:|---|
| Weighted SSSP | 99,897 | 33,848 | dual-oracle PASS |
| Full PageRank | 438,456 | 247,384 | dual-oracle PASS |
| Thresholded residual PageRank | 11,211,825 | 7,432,205 | dual-oracle PASS |

Representative command:

```bash
export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-script-repro-v1/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-script-repro-v1-install
python3 scripts/run_sst_grasu_regraph_hls_weighted.py \
  --profile configs/architectures/grasu_regraph_candidate10_k1_multipart_weighted_v4.json \
  --capability-catalog configs/contracts/grasu_regraph_k1_multipart_capabilities_v4.json \
  --workload tests/data/grasu_regraph_weighted_dynamic_initial.slice \
  --update-workload tests/data/grasu_regraph_weighted_dynamic_update.slice \
  --out-dir /data/tmp/chuxiao/grasu_address_map_v4_weighted_smoke \
  --sst scripts/run_sst_exact_idle_dramsim3.sh --lib-dir build/sst \
  --max-cycles 30000000 --no-build
```

## Evidence boundary

The pre-fix 540K-edge Weighted SSSP matrix passed all functional and request
conservation checks for batches 8, 64, and 4096. It is retained only as a
functional regression. Its cycles, DRAM row statistics, and HBM energy must not
enter publication figures. The paper-scale matrix is rerun from clean output
directories with the corrected profile hashes.
