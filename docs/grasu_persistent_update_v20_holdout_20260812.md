# G+R persistent warm-update v20 holdout

## Decision

The frozen v20 GraSU+ReGraph persistent warm-update timing model passes its
untouched SO/PK FPGA holdout. The holdout did not refit the model or alter its
predeclared thresholds.

The model predicts one warm persistent update invocation as:

```text
simulator update cycles
+ batch launch cycles
+ post-first-shard cycles * max(0, nonempty destination shards - 1)
```

The coefficients were frozen from AU, SU, LJ, and LJ08 before SO/PK simulator
or FPGA holdout results were observed. LJ/LJ08 are development rows in v20 only
because they had already exposed and failed the earlier v19 transfer model.

## Untouched holdout result

| Algorithm | SO abs. err. | PK abs. err. | Median | Max | Gate |
|---|---:|---:|---:|---:|---|
| Weighted SSSP | 32.24% | 1.51% | 16.88% | 32.24% | PASS |
| Connected Components | 3.53% | 8.28% | 5.90% | 8.28% | PASS |
| Thresholded Residual PageRank | 0.35% | 8.59% | 4.47% | 8.59% | PASS |

The gates were frozen at 25% median absolute error and 40% maximum absolute
error per algorithm. All warm FPGA repeat coefficients of variation are below
10%, versus the predeclared 20% maximum.

## Evidence boundary

- This validates persistent **update-only** timing, not graph convergence,
  process startup, or cold graph loading.
- The FPGA statistic is the median of warm repeats 1--4. Repeat 0 is retained
  only as a cold diagnostic.
- PMA state is restored before every repeat. PageRank degree state is also
  restored. All PMA and degree mismatch counters are zero.
- The two fitted terms are routed runtime envelopes. They are not individual
  OpenCL-operation hardware counters.
- SO and PK did not enter fitting. The frozen model SHA-256 is
  `6433b04fdcb5dfb60e75dca283e6063d414faabcb16dab182340a6a928a6255d`.

## Reproduction

The simulator holdout was executed from the v20 contract with the frozen v19
plugin because v20 changes only the timing model and evidence roles:

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3

python3 scripts/analyze_grasu_persistent_update_v20.py \
  --mode validate-holdout \
  --contract configs/contracts/current_fpga_grasu_persistent_update_v20.json \
  --holdout-sim-root \
    /data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_so_pk_holdout_20260812 \
  --holdout-hw-root \
    /data/tmp/chuxiao/grasu_update_only_holdout_v20_000cc91 \
  --model \
    docs/evaluation_refresh_20260810/calibration_v20_grasu_persistent_update_frozen/frozen_model.json \
  --out-dir \
    docs/evaluation_refresh_20260810/calibration_v20_grasu_persistent_update_holdout
```

The tracked holdout directory contains per-case predictions, per-algorithm
summaries, hashes for every simulator and FPGA input, and a manifest declaring
`model_refit=false`.
