# Affected-Fraction FPGA Supplement

November 7, 2026. This folder adds the completed affected-fraction experiment
to the original Figures 7--11 handoff. It is a byte-for-byte copy of the
experiment artifacts delivered in commit `5f14b056fc4a57f76f79567dafceae7c1e10d00b`,
with this reading guide added. It does not rerun, replace or change the
existing Figures 7--11, the frozen November 6 archive, or the paper.

## Files To Use

| Item | File |
| --- | --- |
| Combined figure | [PNG preview](handoff/figures/crossover.png), [vector PDF](handoff/figures/crossover.pdf) |
| One row per attempted point | [points.csv](handoff/data/points.csv) |
| Every warmup, measurement and retained failed attempt | [samples.csv](handoff/data/samples.csv) |
| Curve values and measured crossing brackets | [summary.json](handoff/data/summary.json) |
| Available timing/work fields and definitions | [records.csv](handoff/work/records.csv), [summary.json](handoff/work/summary.json) |
| Exact update batches | [updates.tar.gz](handoff/data/updates.tar.gz) |
| Raw host logs and execution receipts | [host-logs.tar.gz](handoff/data/host-logs.tar.gz) |
| Workload, hardware and campaign manifests | [data/](handoff/data/) |
| Outcome and file digests | [delivery.json](handoff/delivery.json) |
| Independent archive/protocol check | [review.json](handoff/review.json) |
| Python source, shared helpers, configurations, scripts and tests | [crossover-source.zip](crossover-source.zip), [source identity](handoff/source-bundle.json) |

The [complete study guide](../../../../affected_fraction_fpga/README.md)
contains the workload construction, reproduction commands, limitations and
local run index. That canonical study folder remains unchanged in location.
The existing [Figures 7--11 delivery](../LATEST.md) remains a separate selection;
its frozen download does not include this new supplement.

## Result

The x-axis is the CPU-reference fraction of final vertex values changed,
including all declared vertex IDs in the denominator. The y-axis is
G+R / Spine resident wall latency; above 1x favors Spine. These are measured
FPGA results, not simulator predictions.

All 44 primary points were attempted: **42 valid points and two failed
ResPR points**. The package retains 126 formal measured pairs, 42 successful
warmup pairs, two failed primary warmups and two superseded failed warmups.
One valid zero-change PR control stays in the data but is excluded from the
logarithmic plot. Delivery status is `COMPLETED_WITH_FAILURES`.

| Targeted curve | Adjacent measured crossing bracket, changed vertices (%) | Endpoint speedups |
| --- | --- | --- |
| AU SSSP | 0.21076--0.40017 | 1.132x / 0.777x |
| AU CC | 0.010286--0.100722 | 1.976x / 0.728x |
| AU ResPR | 0.013197--0.113336 | 1.069x / 0.504x |
| R19 SSSP | 0.100327--1.068878 | 3.259x / 0.314x |

These brackets apply to the tested targeted workload families, not universal
crossover thresholds. Ordinary 8/64/512/4096-update batches are separate open
markers and can lose earlier; update count, source distribution and host work
also matter. R19 is an R-MAT graph, **not a road network**. AU reaches about
39% changed vertices for SSSP/CC; R19 SSSP reaches 52.61%. No unachieved
50% AU point is presented as a measurement.

## Scope And Failures

Both sides start from the same resident, converged old state and apply the
same batch through checked final state/readback. Initial loading and old-state
convergence are excluded. Host relaunch and in-window preparation remain
included. SSSP/PR use the resident-batch window; CC uses host pack to final
readback. Absolute times across algorithms therefore have different scopes.
Each valid point uses one warmup and three measured pairs, alternating arm
order. The plotted speedup is the ratio of the two median wall times.

SSSP/CC use 150 MHz. PR uses matched derated 140/500/430-MHz clocks after the
nominal route missed timing. PR has fixed per-vertex epsilon `1e-6`, damping
`0.85`, 128 FP32 old-rank rounds and at most 256 correction rounds. A second
epsilon was not tested. Missing device/host counters remain missing; overlapping
kernel durations are not summed into an invented host-time estimate.

ResPR `fan-in-16384` (1.83143% changed) and `fan-in-131072` (14.30326%)
fail in the first Spine propagation round with `overflow=1` and FIFO occupancy
256; the first also reports `owner_status=6`. No speedup is assigned to either.
The intervening 7.20248% point passes, so these failures do not establish a
monotonic capacity threshold. Their precise root cause remains unresolved.
The retained superseded board-download timeout and host CLI mismatch are
distinguished from those two workload-induced failures.

Archive review `PASS` means protocol, logs, medians, clocks and coverage agree;
it does not mean all hardware points passed. No core, SST or HLS changes were
made for this experiment. The largest recorded board-run memory peak was
8.58 GiB, with no OOM event.

## Verify And Redraw

The source zip freezes commit `018b3c888894f1833a2242a2ee222897387a1602`:
SHA256 `d7f537b59c84c1a954fa31e0f70f788029ffafa4cd03b09d146f831de8f2ec87`.
It contains experiment code and repository helpers, not FPGA tools, large old
graphs, host binaries, bitstreams or complete HLS trees. Those dependencies
are indexed by identity in the manifests. Recorded original absolute paths
remain provenance; use the relative paths above to read this portable copy.

From the simulator checkout, replacing the path below with this folder's
absolute path (or using the extracted source zip as the checkout):

```sh
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.review \
  /absolute/path/to/affected_fraction_fpga_20261107/handoff \
  --output /tmp/affected-fraction-review.json
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.plot \
  /absolute/path/to/affected_fraction_fpga_20261107/handoff/data/summary.json \
  /tmp/affected-fraction-crossover
```

The plotter is Python/Matplotlib with TX Typewriter. Redrawing writes fresh
PNG/PDF files; it does not alter the frozen CSVs or measurements.
