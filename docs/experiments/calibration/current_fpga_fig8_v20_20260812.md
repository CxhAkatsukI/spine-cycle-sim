# Current-FPGA Figure 8 v20

## Result

The current Figure 8 setup-inclusive update-only matrix completed all seven
unique executions. Every row passed the update oracle, structural-work gate,
memory-ledger gate, and frozen-evidence identity checks.

At 512 logical updates, Delta.hls throughput relative to normalized sharded-K4
GraSU+ReGraph is:

| Dataset | Delta.hls | G+R | Speedup |
|---|---:|---:|---:|
| AU | 27.149 kupdates/s | 2.415 kupdates/s | 11.24x |
| SU | 17.897 kupdates/s | 1.726 kupdates/s | 10.37x |
| WK | 10.527 kupdates/s | 0.570 kupdates/s | 18.48x |
| SO | 0.453 kupdates/s | 0.024 kupdates/s | 18.94x |
| PK | 0.190 kupdates/s | 0.031 kupdates/s | 6.09x |

The AU batch-size sweep is:

| Updates per batch | Delta.hls | G+R | Speedup |
|---:|---:|---:|---:|
| 64 | 3.430 kupdates/s | 0.299 kupdates/s | 11.47x |
| 512 | 27.149 kupdates/s | 2.415 kupdates/s | 11.24x |
| 4,096 | 197.543 kupdates/s | 19.625 kupdates/s | 10.07x |

## Timing and calibration boundary

This is setup-inclusive **update-only** throughput. Each row includes measured
host preprocessing, modeled PCIe transfer and launch/synchronization overhead,
and frozen calibrated persistent device-update cycles. It excludes graph
propagation and convergence by construction.

The current admission gate is deliberately narrower than a whole-machine Spine
calibration claim:

- Delta.hls uses the v15 maintenance component model. Its SSSP maintenance
  holdout has 9.25% median and 16.15% maximum absolute error.
- G+R uses the v20 persistent update model. Its untouched SO/PK holdout passes
  all three algorithms under the predeclared 25% median and 40% maximum error
  gates.
- The Spine v15 whole-machine holdout remains `FAIL`; it is irrelevant to this
  update-only timing window and is retained as an explicit limitation rather
  than being hidden.
- Neither simulator process wall time nor graph-compute cycles enter this
  result.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3

python3 scripts/run_current_fig8_update_only_matrix.py \
  --evidence-root \
    /data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig8_20260812 \
  --jobs 2 \
  --memory-reserve-gib 72 \
  --memory-poll-seconds 10

python3 scripts/export_persistent_update_setup_fig8.py \
  --evidence-root \
    /data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig8_20260812 \
  --out-dir docs/evaluation_refresh_20260810/fig8_current_v20 \
  --status PASS_CURRENT_MODEL_DATA \
  --cross-dataset au:AU \
  --cross-dataset su:SU \
  --cross-dataset wk:WK \
  --cross-dataset so:SO \
  --cross-dataset pk:PK \
  --batch-count 64 \
  --batch-count 512 \
  --batch-count 4096
```

The tracked manifest records every input comparison and case-manifest hash,
the frozen architecture and calibration contracts, both SST plugin hashes,
both frozen model hashes, and both holdout-analysis hashes.
