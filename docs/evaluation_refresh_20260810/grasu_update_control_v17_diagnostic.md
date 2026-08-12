# G+R update-control diagnostic replay

## Scope

This checkpoint replays the v13 pre-registered shard-only timing formula after
the current CC host layout and label semantics were corrected. AU and SU are the
only fitted rows. WK and R19 are never admitted to the fit. Because their values
were inspected before the replacement contract was written, this is diagnostic
replay evidence, not an independent holdout claim.

The exact contract is
`configs/contracts/current_fpga_grasu_update_control_v15.json`. It pins the v15
SST plugin and all three current sharded-K4 profiles. The fitted form remains:

```
hardware_update_cycles = simulator_update_cycles
                       + control_cycles_per_nonempty_shard
                         * nonempty_destination_shards
```

PMA footprint and operation counters are archived in the manifests but do not
enter this inherited formula.

## Result

Calibration passes the frozen limits:

| Algorithm | AU/SU median absolute error | AU/SU maximum absolute error |
| --- | ---: | ---: |
| Weighted SSSP | 3.28% | 4.64% |
| Connected components | 5.78% | 6.11% |
| Residual PageRank | 8.53% | 9.25% |

The WK/R19 diagnostic replay fails transfer:

| Algorithm | WK/R19 median absolute error | WK/R19 maximum absolute error |
| --- | ---: | ---: |
| Weighted SSSP | 37.28% | 52.79% |
| Connected components | 72.12% | 73.80% |
| Residual PageRank | 45.60% | 57.84% |

Therefore nonempty-shard count alone is not a transferable update timing model.
These failed rows cannot be used to refit a model and then be relabeled as
holdout evidence. A mechanism revision must be frozen before LJ/LJ08 are opened
as the next transfer datasets.

## HLS path correction

`kernel_process_cache.cpp` contains an alternate path that loads and stores the
entire `MAX_CACHE_SEGMENT` region. That path is not active in the routed xclbins
used here. The recorded compile commands define
`GRASU_PURE_PIPELINE_DIRECT_CACHE`, selecting `process_cache_direct()`, which
performs only update-addressed PMA read-modify-write operations. Charging a
fixed 131072-segment cache sweep would therefore be an incorrect explanation of
the board timing.

The remaining diagnosis must separate three effects that are currently folded
into the OpenCL event union: per-CU command submit/start delays, direct PMA RMW
and binary-search memory service, and contention/completion backpressure among
the nine update CUs (ten for PageRank). Host event timelines are the next source
of evidence; a footprint extension remains exploratory until validated on
untouched workloads.

## Reproduction

```bash
python3 scripts/analyze_current_fpga_grasu_update_control_v13.py \
  --mode freeze \
  --contract configs/contracts/current_fpga_grasu_update_control_v15.json \
  --observation-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v15_update_observability_20260812 \
  --frozen-dir docs/evaluation_refresh_20260810/calibration_v17_grasu_update_frozen

python3 scripts/analyze_current_fpga_grasu_update_control_v13.py \
  --mode holdout \
  --contract configs/contracts/current_fpga_grasu_update_control_v15.json \
  --observation-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v15_update_observability_20260812 \
  --frozen-dir docs/evaluation_refresh_20260810/calibration_v17_grasu_update_frozen \
  --out-dir docs/evaluation_refresh_20260810/calibration_v17_grasu_update_diagnostic_replay
```

The second command intentionally exits with status 2 and writes a `FAIL`
manifest. That exit is the expected model verdict.
