# Revised G+R Versus Spine: 24 FPGA Comparisons

All three algorithms on all eight full-graph workloads pass their recorded correctness gates.
These are actual resident FPGA wall times, not simulator predictions or fitted cycles.
The package does not establish original-publication performance reproduction or new simulator timing calibration.

## Read This First

- `figure/fpga_speedup.png` is the preview; the PDF is vector output with TX Typewriter (txtt).
- `summary.csv` contains all 24 measured ratios, actual DATA clocks and formal propagation counts.
- `profile/` retains event diagnostics and every formal wall sample, including outliers.
- `code/board_review/` contains byte-identical snapshots of the plot and profile module owners.
- `raw_evidence.tar.gz` contains `evidence/` (raw logs, case reports, matrix, plan and file hashes)
  and `validation/` (original finalizer records, archive recipe and isolated reproduction reviewer).
- `manifest.json` records hashes of every archive payload and readable artifact.
- [Final review receipt](review/README.md) records successful isolated reproduction,
  embedded-font and visual checks; the original manifest and archive are unchanged.
- The adjacent `../implementation_evidence/` package retains implementation checks and failed attempts.

## Measured Ratios

Each value is median G+R wall divided by median Spine wall. Above one favors Spine; below one favors G+R.
No frequency scaling, timing fit or outlier removal is applied.

| Graph | SSSP | CC | ResPR |
| --- | ---: | ---: | ---: |
| AU | 4.304 | 0.144 | 0.398 |
| SU | 6.386 | 0.185 | 0.517 |
| WK | 6.075 | 0.570 | 0.819 |
| SO | 41.697 | 7.308 | 4.482 |
| PK | 75.332 | 3.407 | 2.154 |
| LJ | 89.168 | 10.007 | 3.983 |
| LJ08 | 90.575 | 9.207 | 3.529 |
| R19 | 19.387 | 0.838 | 0.518 |

## Timing And Workload Contract

Both implementations start from the same converged old-graph state and process the same frozen batch
to the checked new result. There is one excluded warmup and three measured pairs with alternating order.
The interval includes update, correction/propagation, host launch/wait, inter-round relaunch and final readback.
Initial graph/PMA creation, initial residency, old-state preload, batch preparation/upload and CPU oracles
are excluded on both sides. This is resident update-to-result latency, not whole-startup latency.

There are eight batch edits: eight directed records for SSSP/ResPR and sixteen reciprocal records for CC.
ResPR uses alpha 0.85 and direct per-vertex epsilon 1e-6, not epsilon divided by V. The frozen PR inputs
are sink-completed transformed workloads. Consult the recorded round counts before claiming propagation.
All eight ResPR cases have zero propagation rounds on both implementations and their CPU oracles:
they measure update/correction/completion, not iterative PR propagation.

SSSP/CC DATA clocks are 150 MHz on both sides. ResPR G+R uses DATA 149/HBM 432 MHz; Spine uses
DATA 150/HBM 448 MHz after automatic clock scaling. G+R hosts use GCC 15.2 -O2; Spine uses -O3.
The tiny SSSP source-active preparation is outside G+R's interval but inside Spine's device path.

## Reproduce Without A Board

Extract into a fresh review directory. The bundled modules need no simulator checkout:

```bash
tar -xzf /path/to/this-package/raw_evidence.tar.gz -C /path/to/fresh-review
PYTHONPATH=/path/to/this-package/code python3 -m board_review.fpga_plot \
  --delivery /path/to/fresh-review/evidence --output /path/to/fresh-figure
PYTHONPATH=/path/to/this-package/code python3 -m board_review.fpga_profile \
  --delivery /path/to/fresh-review/evidence --output /path/to/fresh-profile
```

The `board_review` namespace only packages the two original modules; it adds no numerical logic.
Rendering requires Matplotlib and a working LaTeX installation with txfonts. The provenance files pin
the renderer and analyzer. Both commands verify the copied evidence hashes; neither reruns FPGA jobs.
Rechecking original bitstream/input/source pins additionally requires the external paths in the frozen plan
and the integration repository's `validation/cache_extent/delivery.py`. Large binaries and graphs are not in Git.

The original raw evidence bytes are unchanged. Event unions are not additive stage times, and resident wall
minus event union is not pure host time. The approximately 2.47x ReGraph publication-scale control gap
remains a disclosed limitation. No paper was changed. See the parent `REPORT.md` for conclusions.
