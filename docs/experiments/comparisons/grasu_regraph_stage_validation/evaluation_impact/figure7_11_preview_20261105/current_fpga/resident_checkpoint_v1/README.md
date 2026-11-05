# Resident FPGA Checkpoint

November 5, 2026: **13 measured pairs, 11 pending**, out of the declared
eight-dataset, three-algorithm matrix. This is not a completed all-win handoff.
The paper is unchanged. No projected values, timeouts or older CC measurements
fill missing slots. A hyphen in the preview means pending, not zero or timeout.

- [Data: all 24 statuses](fig7_resident_checkpoint.csv)
- [Grouped preview](figures/fig7_resident_checkpoint.png) /
  [PDF](figures/fig7_resident_checkpoint.pdf)
- [Scope and complete artifact index](scope.json)
- [Hash-checked small receipts and logs](receipts.tar.gz)
- [Exact baseline G/R source controls](../README.md)

## Results

Ratios are G+R wall time / Spine wall time; above 1 favors Spine.

| Dataset | SSSP | CC | ResPR |
| --- | --- | --- | --- |
| AU | 2.03x | pending route/test | 1.77x |
| SU | 2.52x | pending route/test | 2.22x |
| WK | 3.58x | pending route/test | 1.51x |
| SO | 15.07x | pending route/test | 4.74x |
| PK | 12.52x | pending route/test | 13.07x |
| LJ | 20.45x | pending route/test | pending memory/test |
| LJ08 | 24.01x | pending route/test | pending memory/test |
| R19 | 7.01x | pending route/test | pending earlier queue |

Both arms begin with the same old graph and converged state, apply eight
updates, and finish under the common convergence and final-oracle guards.
The resident wall timer includes update handling, host waits/relaunch and
final readback; initial old-state setup is outside. SSSP includes one to three
propagation rounds. Its initial G+R frontier packing is outside the timer,
while the corresponding Spine source-list construction is inside. The CSV
retains absolute milliseconds, rounds, clocks, sample counts and receipt hashes.

## ResPR Host Retime

ResPR uses a [qualified host-only correction cache](https://github.com/jayfeather9/spine-dynamic-graph/commit/b576278).
The old host rebuilt correction over the full graph after each update. The
new cache retains only old-graph/rank information, then reconstructs affected
incoming sums in canonical source order with the same FP32 arithmetic. It
still scans seeds, uploads state and reads back final state. A dangling-status
change falls back to dense correction. CPU qualification compares 160 cases
bit-for-bit, including 74 dense fallbacks; the board samples also pass the
independent final-state oracle. This does not add a device correction engine.

The cache is valid for **one batch** from that old graph/rank. Its construction
and extra memory are outside the resident timer and explicitly reported:

| Dataset | Cache bytes | Old-graph cache preparation, ms |
| --- | --- | --- |
| AU | 17,735,268 | 22.6721 |
| SU | 20,184,996 | 28.4556 |
| WK | 40,686,736 | 60.9913 |
| SO | 281,878,272 | 1,344.03 |
| PK | 224,134,204 | 1,190.86 |

Count this preparation in a setup-inclusive comparison. All five ResPR pairs
have **zero nonempty propagation rounds** at fixed FP32 epsilon 1e-6, not
epsilon/V. They support resident update/correction completion, not a general
propagation advantage. Each retime measures Spine once and reuses the original
matched G+R sample without averaging or rerunning that arm. PK reuses its first
successful qualified retime rather than repeating it in the matrix.

SSSP uses 150/500/450-MHz data/kernel/HBM clocks. ResPR uses matched
140/500/430-MHz clocks on both arms. The nominal ResPR route failed timing;
clock repackaging and board correctness **are not new static timing closure**.
The CSV marks this limitation explicitly.

## Retained Losses And Pending Work

The original PK ResPR result (Spine 102.13 vs. G+R 75.73 ms) remains in the
raw receipts. The separate compact Flickr propagation case still favors G+R:
Spine 35.0756 vs. G+R 4.763413 ms, twelve rounds on each side. It is outside
the declared eight large inputs, but must not be hidden by the zero-round
large-graph results. The old CC AU loss and seven row-overflow failures remain
in the [parent evidence index](../../README.md#where-spine-loses).
The replacement CC image has not supplied a new board measurement here.

## Reproduce

From the simulator repository root, with the indexed original evidence present:

```sh
pkg=docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105
checks=/data/chuxiao/checks/source-retention-repair-20261104
PYTHONPATH=. python3 "$pkg/export_resident_checkpoint.py" \
  --sssp-matrix "$checks/sssp-resident-matrix-banked-v4/matrix.json" \
  --retimes "$checks/respr-host-correction-matrix-v1/matrix.json" \
  --cc-matrix "$checks/cc-warm-stream-2315cae-matrix-v1/matrix.json" \
  --controls "$pkg/current_fpga/gr_controls.csv" \
  --qualification "$checks/spine-respr-incoming-cache-qualification-v2/qualification.json" \
  --spine-host "$checks/spine-respr-incoming-cache-v1/thresholded_residual_pagerank.host" \
  --comparator /home/chuxiao/grasu-regraph-sim-aligned/scripts/compare_resident_fpga_logs.py \
  --output /path/to/fresh-checkpoint
python3 "$pkg/render_current.py" --data "$pkg/current_fpga/gr_controls.csv" \
  --resident-checkpoint /path/to/fresh-checkpoint/fig7_resident_checkpoint.csv \
  --output /path/to/fresh-figures
```

The exporter replays SSSP admission, qualified-host identity, the frozen G+R
references, retime hashes, matched clocks and ratios. It refuses newly measured
CC rows until their separate complete admission replay is implemented; it will
not silently label such rows pending. This directory is a frozen checkpoint;
later results require a fresh export, not edits to its receipts. Large graphs,
state dumps, binaries and toolchains are indexed rather than embedded.
