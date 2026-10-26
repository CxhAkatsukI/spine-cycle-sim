# Spine Host Follow-Up: Fixed-Workload FPGA Comparison

## Status

Complete: all 24 cases and 96 paired runs, including excluded warmups, pass
the terminal correctness, provenance and memory checks. Independent archive
verification, isolated plot/profile reproduction and visual review also pass.
The eight measured cases for each algorithm favor Spine. This is a resident
FPGA comparison, not a new simulator calibration or a publication match.

## Measured Results

Values are `median G+R wall / median Spine wall`; above one favors Spine.
Every row uses three formal paired runs. No sample is discarded and no ratio
is fitted or frequency-normalized. There are no projected or timeout rows.

| Graph | SSSP | CC | ResPR |
| --- | ---: | ---: | ---: |
| AU | 4.355 | 3.868 | 3.083 |
| SU | 6.252 | 5.391 | 3.465 |
| WK | 7.099 | 9.991 | 4.069 |
| SO | 45.991 | 32.647 | 5.589 |
| PK | 74.174 | 57.562 | 3.327 |
| LJ | 96.479 | 78.626 | 5.095 |
| LJ08 | 91.021 | 76.674 | 4.494 |
| R19 | 19.512 | 16.099 | 1.492 |

Ranges are 4.36--96.48x for SSSP, 3.87--78.63x for CC and 1.49--5.59x for
ResPR. **All eight ResPR cases have zero propagation rounds on both sides
and their CPU oracles.** Their ratios demonstrate update/correction/completion
performance, not iterative PageRank propagation. SSSP has one to three rounds;
CC has one or two, with matching formal counts on both implementations.

See the [PNG preview](figure/fpga_speedup.png), [vector PDF](figure/fpga_speedup.pdf),
[exact measurements](summary.csv), [old/new comparison](comparison.csv) and
[independent review](review/README.md). The plot uses the existing Python
renderer and TX Typewriter font; it is not inserted into the paper.

## What Changed

The preceding [v1 package](../fpga_results_v1/README.md) used the optimized
Spine SSSP host but the older CC and ResPR hosts. This follow-up builds CC
and ResPR from the existing clean optimized Spine commit
`cb42376663c534f0bd0c25d271737ca34893135e`; SSSP's executable is unchanged.
No HLS source, FPGA bitstream, clock, input graph, batch, threshold or
measurement boundary is changed.

The shared runtime allocates device-written scratch with initial residency,
using `CL_MIGRATE_MEM_OBJECT_CONTENT_UNDEFINED`. Its host contents are not
algorithm inputs. The device produces every consumed
counted prefix before use, avoiding an implicit first-use upload of an
unused 512-MiB host active-record buffer. It also avoids clearing unused
active-array tails and restoring the full 44-MiB static metadata image.

This is not a new autonomous device execution path. Host correction,
active publication, kernel relaunch, correctness-related consistency checks
and full-state readback remain in their existing paths and measured window.
The before/after matrix compares host versions collected at different times,
not a simultaneous controlled A/B test of each individual optimization.

For example, Spine CC's AU median changes from 82.3447 to 3.05053 ms, and
WK from 132.312 to 7.54539 ms. The unchanged G+R CC medians vary by at most
1.3% between campaigns. The measurements support the shared-host correction,
but do not isolate the contribution of each optimization. SSSP uses the
same executable as v1; its timing variation is not a code improvement.

## Fixed Comparison Contract

- Eight full-graph workloads, each with SSSP, CC and ResPR.
- Both implementations start from the same frozen converged old-graph state
  and apply the same batch to the checked final result.
- One excluded warmup and three formal paired runs, alternating order.
  Ratios use the two formal wall medians, without outlier removal or fitting.
- Boundary: `resident_update_to_final_readback_wall_including_host_relaunch`.
  Update, correction/propagation, host launch/wait, inter-round relaunch and
  final readback are included. Initial graph/PMA creation, residency,
  old-state preload, batch preparation/upload and CPU oracles are excluded
  on both sides. This is not whole-startup latency.
- Eight edits: eight directed records for SSSP/ResPR and sixteen reciprocal
  records for CC. ResPR uses direct per-vertex epsilon `1e-6`, alpha `0.85`
  and the same sink-completed transformed workloads, not epsilon divided by V.
- The frozen eight ResPR cases require zero propagation rounds on both sides
  and their CPU oracles. They measure update/correction/completion, not
  iterative ResPR propagation performance. Retained round counts must
  accompany the speedup ratios.
- SSSP/CC DATA clocks are 150 MHz on both sides. ResPR G+R uses DATA 149/HBM
  432 MHz; Spine uses DATA 150/HBM 448 MHz. Raw walls are not normalized.
- G+R uses GCC 15.2 `-O2`; Spine uses GCC 15.2 `-O3`. The tiny SSSP source-active
  preparation remains outside G+R's interval and inside Spine's device path.

## Package And Reproduction

The reviewed package contains:

| Path | Purpose |
| --- | --- |
| `summary.csv` | All measured walls, ratios, actual clocks and propagation counts |
| `comparison.csv` | Old/new Spine and G+R medians and ratios on the same workload contract |
| `figure/` | PNG preview, vector PDF and plot provenance |
| `profile/` | Every formal wall sample and G+R event-union diagnostics |
| `code/board_review/` | Unchanged plot/profile source snapshots |
| `raw_evidence.tar.gz` | Raw logs, plans, hashes, regression/build receipts and packaging recipe |
| `manifest.json` | Every archived/readable artifact's size and SHA-256 |
| `review/` | Isolated reproduction command, four PDF-review regression tests and review receipt |

The archive contains 638 hash-verified files (26,148,595 uncompressed bytes;
3,432,034 compressed bytes), including every paired raw log. The final
exporter reparses all warmup and formal logs and verifies source, binary,
input, clock and memory records. The old/new contract check retains the
same graph, batch, threshold, boundary, clocks and formal round counts.

For the complete automated archive and reproduction check, use a fresh
directory outside the package:

```bash
python3 -B /path/to/this-package/review/review-fpga-delivery-v2.py \
  --package /path/to/this-package --output /path/to/fresh-review
```

This requires Python 3.12 or later, Matplotlib, NumPy, Pillow, LaTeX with
`txfonts`, MuPDF (`mutool`) and Poppler (`pdffonts`). The recorded environment
is `/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python`. The automatic
receipt leaves visual inspection pending; [the review note](review/README.md)
records the subsequently completed visual check without rewriting the receipt.

To run the two bundled plotting/analysis modules manually without a board,
first create a fresh extraction directory:

```bash
tar -xzf /path/to/this-package/raw_evidence.tar.gz -C /path/to/fresh-review
PYTHONPATH=/path/to/this-package/code python3 -B -m board_review.fpga_plot \
  --delivery /path/to/fresh-review/evidence --output /path/to/fresh-figure
PYTHONPATH=/path/to/this-package/code python3 -B -m board_review.fpga_profile \
  --delivery /path/to/fresh-review/evidence --output /path/to/fresh-profile
```

Rendering requires Matplotlib and LaTeX with txfonts. The two module snapshots
are unchanged from v1; measurements, not plot arithmetic, determine the new
bars. Large bitstreams, executable files and graphs remain external, hash-pinned
inputs rather than Git payloads. Rechecking their original paths needs the
recorded machine and integration exporter.

Machine-local root: `/data/chuxiao/checks/spine-cc-respr-host-20261026`.
`full-matrix-v1/` retains the pre-board optional-pin-size validation failure;
`full-matrix-v2/` is the corrected fresh run. No failed measurement is replaced
or removed. The corrected deduplication validates identical path/hash pins
with optional size metadata; it does not move a measured event.

All 24 saved case memory-event records have zero `high`, `max`, `oom`,
`oom_kill` and `oom_group_kill` events. The finite per-case limits are
16/24/32 GiB, with zero swap and a
24-GiB admission reserve. Admission uses Linux `MemAvailable` plus bounded
evictable ZFS ARC data, not `MemFree` or all cached memory. Supervisor and
build/review jobs have separate finite limits.
The isolated reproduction used a 2-GiB hard cap, 1.5-GiB high watermark and
zero swap, peaking at 124.8 MiB according to systemd's service report.

No paper or frozen simulator figure is edited. This package does not establish
new simulator timing calibration or original-publication performance matching.
Event unions are not additive stage times; wall minus event union is not pure
host time. The accepted approximately 2.47x ReGraph publication-scale gap
remains a separate limitation documented in the parent report.
