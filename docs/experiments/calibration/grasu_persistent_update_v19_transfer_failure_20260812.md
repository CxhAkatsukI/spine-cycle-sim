# G+R persistent-update v19 transfer failure

The v19 model was frozen on AU and SU before observing LJ and LJ08. It predicts
warm update-only FPGA cycles as raw execution-driven simulator update cycles
plus one algorithm-specific constant for every nonempty destination shard.

All six LJ/LJ08 simulator executions pass correctness and memory-ledger checks.
The frozen transfer gate nevertheless fails:

| Algorithm | Median absolute error | Maximum absolute error |
|---|---:|---:|
| Weighted SSSP | 31.47% | 44.42% |
| Connected Components | 27.04% | 31.77% |
| Residual PageRank | 11.45% | 16.70% |

The model was not refit on these holdout rows. The failure shows that a single
per-shard constant does not capture all persistent warm-launch costs. The most
visible miss is LJ08 Weighted SSSP, whose repeated FPGA measurements contain a
stable extra first-shard interval that is absent from the raw simulator update
path.

The next model version may use LJ/LJ08 only as declared development evidence.
It must be frozen before observing a new SO/PK transfer set; SO/PK must not be
used for fitting or model selection.

## Reproduction

```bash
python3 scripts/analyze_grasu_persistent_update_v19.py \
  --mode validate-transfer \
  --simulator-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v19_streaming_transfer_20260812 \
  --hardware-root /data/tmp/chuxiao/grasu_update_only_transfer_1577c60 \
  --model docs/evaluation_refresh_20260810/calibration_v19_grasu_persistent_update_frozen/frozen_model.json \
  --out-dir docs/evaluation_refresh_20260810/calibration_v19_grasu_persistent_update_transfer
```
