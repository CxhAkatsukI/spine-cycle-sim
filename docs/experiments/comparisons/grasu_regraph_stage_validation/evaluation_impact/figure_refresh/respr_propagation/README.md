# ResPR With Actual Propagation

This simulator-only follow-up reruns three historical input pairs using the
current Spine and G+R paths and **fixed per-vertex `epsilon=1e-6`**, without
dividing by vertex count. It does not modify the paper or earlier evidence.

**Result: all three cases propagate nonempty work, but Spine loses on all
three.** Restoring the historical threshold does not establish a general
ResPR latency advantage. The preceding [AU/SU/WK fixed-threshold wins](../respr_fixed_epsilon/README.md)
have zero active correction seeds and must not substitute for this test.

## Results

Cycles are simulator predictions, not measured FPGA cycles. Speedup is
`G+R cycles / Spine cycles`; below one means G+R is faster.

| Input | Vertices | Initial directed edges | Spine cycles | G+R cycles | Speedup |
| --- | ---: | ---: | ---: | ---: | ---: |
| Flickr (FL) | 2,552 | 8,192 | 918,281 | 508,412 | 0.554 |
| AskUbuntu (AU540) | 94,931 | 540,000 | 833,591 | 542,821 | 0.651 |
| AskUbuntu (AU904) | 156,289 | 903,774 | 678,526 | 466,792 | 0.688 |

G+R is approximately **1.81 / 1.54 / 1.45 times faster**, respectively.
Both arms pass the current independent-rank/residual gate and drain their
physical request ledgers. The fixed residual threshold is not a fixed
global rank-error guarantee; actual errors are retained below.

| Input | Initial active vertices | Spine nonempty rounds | Active vertex visits | Spine edges read/computed | G+R live edges scanned |
| --- | ---: | ---: | ---: | ---: | ---: |
| FL | 133 | 12 | 785 | 9,162 | 106,704 |
| AU540 | 17 | 2 | 20 | 586 | 1,620,048 |
| AU904 | 12 | 1 | 12 | 314 | 1,807,580 |

The latter two cases really are sparse propagation, not just update checks.
The G+R round counts are 13 / 3 / 2; they need not equal Spine's 12 / 2 / 1
to satisfy the same stopping rule. The G+R scan ledger counts every updated
graph edge in every round; it does not count only edges with active sources.

## Why Sparse Work Still Loses

The current Spine residual-PR implementation reduces edge work but still
performs a **full-vertex Apply sweep each nonempty round**:

- `begin_apply_tile` chooses the full remaining tile, while
  `next_unapplied_tile` and `advance_after_apply_tile` also visit empty tiles.
- Apply reads each tile vertex and writes every applied vertex's residual,
  even when most vertices are inactive.

See [the tile traversal and Apply implementation](../../../../../../../cpp/src/spine_pagerank.cpp).
For AU540, just one residual read and write per vertex over two rounds is
`94,931 * 8 * 2 = 1,518,896` bytes, close to the observed total 1,551,828
Spine bytes. AU904 similarly gives 1,250,312 versus 1,273,740 observed bytes.
Correction itself takes only 1,240 / 1,923 / 2,002 predicted cycles, far below
the total window. This is source-and-ledger evidence of dense vertex work,
not a hardware-calibrated attribution of every cycle to one stage.

G+R/Spine accepted-byte ratios remain **43.79 / 25.98 / 43.37**, but modeled
all-channel HBM energy ratios are **0.593 / 0.692 / 0.770**. Less traffic does
not imply less time or less total HBM energy when access scheduling and
background/refresh energy differ. No timing parameter was changed to improve
the outcome; this turn adds input selection and passive work counters only.

## Exact Scope And Historical Comparison

- Each batch has eight logical reciprocal insertions, hence sixteen physical
  directed update records. These are real-topology projections/slices and
  constructed bridge updates, not eight full raw temporal datasets. FL is
  only an 8,192-edge slice; AU540/AU904 are compacted reciprocal inputs.
- Both arms receive identical old-rank and independent new-oracle state
  hashes. They start with resident old convergence and include maintenance,
  device preparation and propagation to the configured stopping rule.
  Host preparation, DMA, launch/relaunch and readback are excluded on both.
- Current preparation converges an independent double-precision Jacobi
  computation to successive L1 difference below `1e-12`, then converts the
  old state to FP32. Historical preparation used FP32 with its own stopping
  rule. These are the same historical graph/batch inputs, **not** an exact
  replay of the old initial-state recipe or old K1 implementation.
- Historical K1 screening reported about 3.26 / 9.53 / 13.28 times Spine
  speedup on these input pairs. Those old cycles are not reused. Comparing
  them with this current-model run is not a controlled ablation of K1/K4,
  resource count, memory modeling or old-state precision.
- Current G uses finite natural-geometry/shared-metadata PMAs; R selects
  `prefetch_gather_reuse` with algorithm-specific Apply and timed PR
  preparation. Original-G and original warm residual-PR performance parity
  remain unadmitted. SSSP agreement cannot admit ResPR performance.
- Spine correction remains **oracle-directed timed replay**: memory work is
  charged, but functional seeds are not derived from returned AXI data.
  This is not production-HLS equivalence or new FPGA timing calibration.
- Both arms use 150 MHz, direct DRAMSim3 feedback and the same 32-channel
  backend budget. Their internal port/state layouts differ; this is not a
  strict same-resource A4 reproduction. Energy includes all 32 channels,
  including idle-channel background and refresh, not FPGA board/ASIC power.

Actual maximum rank errors versus the double oracle are approximately
`7.26e-5 / 5.22e-6 / 2.32e-6` for both arms. L1 errors are approximately
`1.75e-3 / 1.42e-4 / 8.58e-5`. The acceptance bound `V*epsilon/(1-damping)`
is substantially looser; the complete residual arrays and printed bounds
are retained rather than claiming uniform global accuracy.

## Review And Reproduce

| Path | Contents |
| --- | --- |
| `data/propagation_comparison.csv` | All three outcomes, work counts, cycles, traffic/energy ratios and oracle errors |
| `data/summary.json` | Machine-readable scope, model boundary and results |
| `evidence/index.json` | Complete portable archive membership and hashes |
| `evidence/evidence.tar.gz` | Graphs/batches/manifests, frozen sources, raw commands/logs, full states, round CSVs, DRAMSim3 reports and core gates |
| `TEST_REPORT.md` | Verification, resource bounds and remaining limits |

The cohesive implementation owner is
`spine_cycle_sim/experiments/evaluation_impact/figure_refresh/multialgorithm/`.
`matrix.py` declares inputs, `study.py` runs them, and
`propagation_followup.py` audits and seals this separate scope. It does not
relax the earlier nine-pair delivery's admission checks.

Offline verification does not need the original `/data` output directory:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.propagation_followup \
  --output docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure_refresh/respr_propagation \
  --verify
```

To rerun from the repository root, use fresh paths/unit names and an allowed
CPU. First run `multialgorithm.core_gates --output FRESH_CORE_GATES` in a
separate service with the same finite memory limits. Then run:

```bash
systemd-run --user --wait --pipe --collect --unit=respr-nonempty-rerun \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=10800 --working-directory="$PWD" /usr/bin/python3 -m \
  spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.study \
  --output FRESH_MATRIX --core FRESH_CORE --cpu 7 --timeout 1800 \
  --algorithms ResPR --case-set historical-residual-u8 --residual-epsilon 1e-6
```

The report retains exact compiler/dependency pins; external SST, DRAMSim3,
compiler and linked binaries are not bundled. Packaging uses fresh output
and `--report FRESH_MATRIX/results.json --core-tests FRESH_CORE_GATES/results.json`
with the offline-verification module above. Original run roots are under
`/data/chuxiao/experiments/respr_nonempty_20261024/`.

**Conclusion boundary:** this completes the requested nonempty-propagation
diagnostic, not baseline-publication reproduction or a full evaluation. It
does not support retaining a universal ResPR speedup claim from the older
figures, nor establish that measured FPGA results must reverse identically.
