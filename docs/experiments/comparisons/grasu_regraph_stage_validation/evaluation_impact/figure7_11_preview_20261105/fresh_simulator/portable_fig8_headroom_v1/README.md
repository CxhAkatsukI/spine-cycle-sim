# Same-Host L4 Fig. 8 Follow-Up

November 5, 2026. Five ten-batch comparisons and all three fixed-total batch
counts are complete. Both panels use the same CPU, compiler, affinity and
explicit L4 bootstrap policy. These are **measured CPU preparation plus
simulated device/transfer predictions, not FPGA measurements**. The earlier
[L2 cohort and PK capacity failure](../portable_fig8/README.md) remain intact.

## Results

Ratios are G+R time / Spine time. Above 1 favors Spine.

| Dataset, 4,096 total updates in ten batches | Spine, s | G+R, s | Ratio |
| --- | ---: | ---: | ---: |
| AU | 0.062575 | 0.218883 | 3.498x |
| SU | 0.092686 | 0.331987 | 3.582x |
| WK | 0.121460 | 1.082171 | 8.910x |
| SO | 4.045749 | 27.235052 | 6.732x |
| PK | 8.254767 | 12.423498 | 1.505x |

| AU, fixed 131,072 updates | Spine, s | G+R, s | Ratio |
| --- | ---: | ---: | ---: |
| 10 batches | 0.137743 | 0.250965 | 1.822x |
| 100 batches | 0.233248 | 0.260214 | 1.116x |
| 1,000 batches | 0.489373 | 0.285333 | **0.583x: G+R wins 1.715x** |

The 1,000-batch loss is retained. Spine's modeled device term grows from
0.0801 to 0.4219 s across the sweep, while its measured host preparation
stays around 0.057 s. Thus this loss is not explained by slower CPU
preparation. SO/PK ten-batch totals, conversely, are dominated by preparation:
Spine 4.019/8.207 s versus G+R 26.814/12.309 s; see the CSV for exact terms.

## Boundary And Version

One Release host sample per arm; Xeon Platinum 8375C, pinned CPU 20,
GCC 15.2, numerical runner commit `05aff52b785a69d675baa85399753709738c7bef`.
State persists across chronological batches. Initial preparation and logical
upload are charged once; each batch adds its host/device update work,
logical transfer and 10 us launch. The formula is host preparation plus
device cycles / 150 MHz, logical H2D bytes / 12 GB/s, and launch time.
Parsing, oracle work, runtime allocation, XRT and final readback are excluded.
This is update-only, **not propagation to convergence**.

L4 places the initial Spine hierarchy at level 4 or above instead of the
earlier L2 minimum. This gives carry headroom and avoids the retained PK L2
failure. It is an explicit configuration change, not a repair to old results
or proof of HLS bootstrap equivalence. The core source is unchanged. G uses
shared metadata and future-batch-union reservation, not the four-copy routed
G layout. These profiles have not passed complete-image FPGA admission.

## Files And Checks

- [Ten-batch CSV](fig8_ten_batch.csv), [scope](scope.json),
  [raw receipts and frozen reference](receipts.tar.gz).
- [Batch-sweep CSV](batch_sweep/fig8_batch_sensitivity.csv),
  [scope](batch_sweep/scope.json), [raw receipts](batch_sweep/receipts.tar.gz).
- [Combined PNG](figures/fig8_update_prediction_headroom.png) and
  [PDF](figures/fig8_update_prediction_headroom.pdf).

Exports reparse the raw counters, formula, configuration and input hashes;
both panels must share the complete CPU/compiler/source/bootstrap cohort and
the same frozen smoke reference. Each sweep uses identical graph/update
bytes. The renderer rejects incomplete, mismatched or edited CSV/scope pairs.
All eight comparisons have the recorded exact-reference smoke match; this
checks numerical portability, not FPGA latency calibration.

Execution roots on the recorded remote host are
`/data/chuxiao/fig8-portable-20261105/headroom-{au,su,wk,so}-v4`,
`headroom-pk-v3`, and `headroom-sweep-b{10,100,1000}-v2`. Sweep v1 failed
configuration because Ninja was not on PATH; those failures remain in the
remote `headroom-sweep-b*-v1` directories. The successful v2 changes PATH,
not numerical settings. Large inputs, runtime/compiler binaries and build
products are hash-indexed, not embedded. The checked export used a separate
`export-source-73ac09e2` checkout; it did not modify the frozen runner.

## Reproduce

From the simulator repository root, with Matplotlib, txfonts and dvipng:

```sh
pkg=docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105
python3 "$pkg/render.py" --headroom-fig8
```

To repeat the checked export on the recorded remote host:

```sh
base=/data/chuxiao/fig8-portable-20261105
exporter=spine_cycle_sim.experiments.evaluation_impact.figure_refresh.portable_evidence
python3 -m "$exporter" freeze --reference "$base/headroom-pk-v3/results.json" --output /tmp/l4-reference.json
python3 -m "$exporter" export --reference /tmp/l4-reference.json \
  --case AU "$base/headroom-au-v4/results.json" --case SU "$base/headroom-su-v4/results.json" \
  --case WK "$base/headroom-wk-v4/results.json" --case SO "$base/headroom-so-v4/results.json" \
  --case PK "$base/headroom-pk-v3/results.json" --output /tmp/l4-datasets
python3 -m "$exporter" sweep --reference /tmp/l4-reference.json \
  --cohort /tmp/l4-datasets/scope.json \
  --case 10 "$base/headroom-sweep-b10-v2/results.json" \
  --case 100 "$base/headroom-sweep-b100-v2/results.json" \
  --case 1000 "$base/headroom-sweep-b1000-v2/results.json" --output /tmp/l4-sweep
```

Do not combine these host times with the earlier EPYC or L2 cohorts. The
renderer uses the supplied GraphyFlow construction, TX Typewriter and the
same density-8 hatches as the other current previews.
