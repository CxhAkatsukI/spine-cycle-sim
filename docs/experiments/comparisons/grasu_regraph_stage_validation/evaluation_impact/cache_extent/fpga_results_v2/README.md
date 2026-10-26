# Spine Host Follow-Up: Fixed-Workload FPGA Comparison

## Status

The independent AU gate passes for CC and ResPR. The complete frozen
24-case matrix is running; this directory is not yet a final delivery.
Do not substitute the AU gate for the full-matrix measurements.

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

After terminal verification, the package contains:

| Path | Purpose |
| --- | --- |
| `summary.csv` | All measured walls, ratios, actual clocks and propagation counts |
| `comparison.csv` | Old/new Spine and G+R medians and ratios on the same workload contract |
| `figure/` | PNG preview, vector PDF and plot provenance |
| `profile/` | Every formal wall sample and G+R event-union diagnostics |
| `code/board_review/` | Unchanged plot/profile source snapshots |
| `raw_evidence.tar.gz` | Raw logs, plans, hashes, regression/build receipts and packaging recipe |
| `manifest.json` | Every archived/readable artifact's size and SHA-256 |
| `review/` | Isolated reproduction command and review receipt |

Extract into a fresh directory and reproduce without a board:

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

The finite per-case memory limits are 16/24/32 GiB, with zero swap and a
24-GiB admission reserve. Admission uses Linux `MemAvailable` plus bounded
evictable ZFS ARC data, not `MemFree` or all cached memory. Supervisor and
build/review jobs have separate finite limits.

No paper or frozen simulator figure is edited. This package does not establish
new simulator timing calibration or original-publication performance matching.
Event unions are not additive stage times; wall minus event union is not pure
host time. The accepted approximately 2.47x ReGraph publication-scale gap
remains a separate limitation documented in the parent report.
