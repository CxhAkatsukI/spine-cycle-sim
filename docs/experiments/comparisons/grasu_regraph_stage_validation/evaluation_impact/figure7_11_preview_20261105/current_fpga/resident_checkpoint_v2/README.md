# Resident FPGA Checkpoint: Fifteen Pairs

November 5, 2026. **15 measured pairs, nine missing** in the declared
eight-dataset, three-algorithm matrix. This adds LJ and R19 ResPR to the
frozen [thirteen-pair checkpoint](../resident_checkpoint_v1/README.md).
No paper edits, projected bars, substitute old CC results or averaging.

- [All 24 data/status rows](fig7_resident_checkpoint.csv).
- [Grouped PNG](figures/fig7_resident_checkpoint.png) and
  [PDF](figures/fig7_resident_checkpoint.pdf).
- [Scope, source map and artifact index](scope.json).
- [Replayed small receipts and logs](receipts.tar.gz).
- [Exact baseline G/R controls](../README.md).

## Results

Ratios are G+R wall time / Spine wall time; above 1 favors Spine.

| Dataset | SSSP | CC | ResPR |
| --- | ---: | --- | ---: |
| AU | 2.03x | pending route/test | 1.77x |
| SU | 2.52x | pending route/test | 2.22x |
| WK | 3.58x | pending route/test | 1.51x |
| SO | 15.07x | pending route/test | 4.74x |
| PK | 12.52x | pending route/test | 13.07x |
| LJ | 20.45x | pending route/test | 19.29x |
| LJ08 | 24.01x | pending route/test | pending after pressure-guard aborts |
| R19 | 7.01x | pending route/test | 6.79x |

Same old graph/converged state, eight updates, common final oracle and
convergence rule. Resident wall time includes host waits/relaunch and final
readback, excluding initial old-state setup. SSSP has one to three rounds;
G+R initial frontier packing is outside the timer, while Spine source-list
construction is inside. All seven ResPR pairs have **zero nonempty
propagation rounds** at fixed FP32 epsilon 1e-6, not epsilon/V. They do not
establish a propagation speedup.

Each ResPR retime measures the qualified Spine host once and reuses its
frozen G+R sample. The old-graph/rank correction cache is valid for one batch,
is built outside the resident window and is not a device correction engine.
New cache/preparation costs are LJ **478,545,740 bytes / 3,445.11 ms** and R19
**77,368,796 bytes / 380.705 ms**; count these in setup-inclusive results.
The CSV retains the first five costs unchanged.

SSSP runs at 150/500/450-MHz data/kernel/HBM clocks. ResPR matches
140/500/430 MHz on both arms after its nominal route failed timing;
repackaging and successful board tests are **not new static timing closure**.
All stage controls use the exact corresponding G+R image. This is matched
public-source-port retention, not reproduction of publication throughput.

## Missing Cases And Negative Evidence

The replacement CC route is still building; its old AU loss and seven
row-overflow failures remain in the parent index. LJ08 ResPR has no accepted
pair here: strict ARC-profile attempts stopped during old-state loading,
before a timing could be admitted. Recent failed receipts remain at
`/data/chuxiao/checks/source-retention-repair-20261104/respr-dual-arc-lj08-retry-v{2,3,4}`.
They report zero cgroup OOM events, roughly 20-GiB peaks and full PSI around
1.1%, despite effective reserve exceeding 32 GiB. They are protection aborts,
not measured losses or timeouts. A new memory profile cannot retroactively
accept them. ARC reclaim and containment are documented in the
[board memory policy](../../../../../../../implementation/runtime/board_arc_admission.md).

The original PK ResPR loss, compact Flickr twelve-round propagation loss
(35.08 vs. 4.76 ms), and legacy FullPR losses remain evidence. Thus these
fifteen wins are **not** a completed all-win result for every workload.

## Reproduce

From the repository root with original indexed inputs present:

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
  --output /path/to/new-checkpoint
python3 "$pkg/render_current.py" --resident-checkpoint /path/to/new-checkpoint/fig7_resident_checkpoint.csv \
  --output /path/to/new-checkpoint/figures
```

The full original eight-status retime matrix comes first; explicit remainder
fragments follow. Their raw bytes and per-dataset origins are archived. A
later failure/pending status cannot replace an accepted sample; two distinct
measured candidates are rejected rather than selecting the faster value.
Large graph/state arrays, binaries and toolchains are hash-indexed, not
embedded. This directory is a frozen checkpoint; later results need a new
export directory.
