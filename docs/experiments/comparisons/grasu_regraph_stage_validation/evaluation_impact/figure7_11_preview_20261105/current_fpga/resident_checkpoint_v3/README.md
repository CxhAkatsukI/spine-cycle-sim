# Resident FPGA Checkpoint: Sixteen Pairs

November 5, 2026. **16 measured pairs, eight CC pairs missing** in the
declared eight-dataset, three-algorithm matrix. This adds the completed
LJ08 ResPR pair to the frozen [fifteen-pair checkpoint](../resident_checkpoint_v2/README.md).
No paper edits, projections, replacement old CC bars or averaging.

- [All 24 data/status rows](fig7_resident_checkpoint.csv).
- [Grouped PNG](figures/fig7_resident_checkpoint.png) and
  [PDF](figures/fig7_resident_checkpoint.pdf).
- [Scope, source map and hashes](scope.json).
- [Replayed original small receipts/logs](receipts.tar.gz).
- [Exact baseline G/R controls](../README.md).

## Results And Scope

Ratios are G+R wall time / Spine wall time; above 1 favors Spine.

| Dataset | SSSP | CC | ResPR |
| --- | ---: | --- | ---: |
| AU | 2.03x | pending route/test | 1.77x |
| SU | 2.52x | pending route/test | 2.22x |
| WK | 3.58x | pending route/test | 1.51x |
| SO | 15.07x | pending route/test | 4.74x |
| PK | 12.52x | pending route/test | 13.07x |
| LJ | 20.45x | pending route/test | 19.29x |
| LJ08 | 24.01x | pending route/test | 19.94x |
| R19 | 7.01x | pending route/test | 6.79x |

Each pair starts from the same converged old graph/state, applies eight
updates and checks the final result under the same convergence rule. The
resident wall boundary includes host waits/relaunch and final readback,
excluding initial old-state setup. G+R's initial frontier packing is outside
this boundary; Spine's source-list construction is inside. SSSP takes one
to three rounds. **All eight ResPR pairs have zero nonempty propagation
rounds** at fixed per-vertex FP32 epsilon 1e-6 (not epsilon/V); these rows do
not establish propagation speedup.

LJ08 measures both arms once: **Spine 16.5773 ms, G+R 330.583238 ms**,
ratio 19.941923. Both final correctness checks pass. The other seven ResPR
rows each measure the qualified Spine host once and reuse their exact frozen
G+R sample, explicitly marked in the CSV. No faster sample is selected.

The qualified host's old-graph/rank correction cache is valid for one batch
and built outside the resident window, not by a device correction engine.
For LJ08 it uses **546,285,752 bytes**, with **4,042.49 ms** preparation
reported separately. Include this preparation when claiming setup-inclusive
performance. Costs for every other ResPR row remain in the CSV.

SSSP uses 150/500/450-MHz data/kernel/HBM clocks. ResPR uses matched
140/500/430 MHz after its nominal route failed timing. Repackaging and
correct board execution do not establish new static timing closure.
G/R controls use the exact corresponding baseline images: this is retention
against named public-source ports, not reproduction of published throughput.

The earlier CC AU loss/row-overflow failures, original PK ResPR host loss,
compact Flickr propagation loss and legacy FullPR losses remain in the
[parent evidence index](../../README.md#where-spine-loses). The replacement
CC build and its [guarded follow-ups](../cc_resume_v2/README.md) are still
pending. Original CC status strings are retained in the CSV; none supply
a measured bar. These sixteen wins are not a complete all-win result.

## Provenance And Reproduction

LJ08's completed service is
`gr-respr-qualified-lj08-prelaunch-20261105-v2.service`, invocation
`0c514a3df92a4f8a9351a87a952a84f3`, run from frozen simulator source
`f684a1c7`. Its original receipt SHA-256 is
`5e8d128ff834a5fd5511015b21bfd197c147a0c821f62b13d8be6b53cbbe0d9a`.
The measured execution completed at 15:14 UTC with a 26.5-GiB service peak,
within its 32-GiB hard limit and zero task swap. Earlier protection-aborted
attempts are not retroactively accepted.

From the repository root with indexed original evidence available:

```sh
pkg=docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105
checks=/data/chuxiao/checks/source-retention-repair-20261104
PYTHONPATH=. python3 "$pkg/export_resident_checkpoint.py" \
  --sssp-matrix "$checks/sssp-resident-matrix-banked-v4/matrix.json" \
  --retimes "$checks/respr-host-correction-matrix-v1/matrix.json" \
  --retimes "$checks/respr-host-correction-arc-lj-retry-v3/matrix.json" \
  --retimes "$checks/respr-host-correction-arc-remainder-v2/matrix.json" \
  --cc-matrix "$checks/cc-warm-stream-2315cae-matrix-v1/matrix.json" \
  --controls "$pkg/current_fpga/gr_controls.csv" \
  --qualification "$checks/spine-respr-incoming-cache-qualification-v2/qualification.json" \
  --spine-host "$checks/spine-respr-incoming-cache-v1/thresholded_residual_pagerank.host" \
  --comparator /home/chuxiao/grasu-regraph-sim-aligned/scripts/compare_resident_fpga_logs.py \
  --qualified-pair "$checks/respr-qualified-lj08-prelaunch-v2/results.json" \
  --output /path/to/fresh-checkpoint
python3 "$pkg/render_current.py" \
  --resident-checkpoint /path/to/fresh-checkpoint/fig7_resident_checkpoint.csv \
  --output /path/to/fresh-checkpoint/figures
```

Export validates source controls, clocks, host/kernel hashes, qualification,
logs and analysis. It rejects duplicate measured candidates instead of
selecting a faster result. The first full status matrix and later explicit
fragments are archived unchanged. Large graphs/states, binaries and tools
remain hash-indexed rather than embedded. Plotting reuses the checked Python
GraphyFlow/TX Typewriter style. The older `CURRENT.md` review/archive remains
frozen at fifteen pairs; this is an independent incremental export.
