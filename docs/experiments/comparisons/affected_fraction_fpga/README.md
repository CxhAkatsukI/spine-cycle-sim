# Affected-Fraction FPGA Crossover

This experiment varies the **actual fraction of final vertex values changed**,
not batch size or the initial active set, and measures G+R / Spine resident
wall latency. It supplements, and does not replace, the frozen Figures 7--11.
The paper is not edited. Raw evidence is retained outside the checkout;
completed measurements are exported here with their input and host-log archives.

An identical author-facing copy is also available in the original evaluation
handoff as [affected_fraction_fpga_20261107](../grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105/affected_fraction_fpga_20261107/README.md).
That renamed supplement includes a reading guide, the complete `handoff/`
and the source zip; existing Figures 7--11 and their frozen archive are unchanged.

## Results And Delivery

These are FPGA wall measurements, not simulator predictions. A value above
1x favors Spine; below 1x favors G+R. **Spine does not win at all affected
fractions.** Each targeted family crosses 1x in the tested range.

All 44 unique primary points were attempted: 42 have valid paired timings,
and two failed. The archive contains 126 formal pairs, 42 successful warmup
pairs, two failed primary warmups and two superseded failed warmups (172
sample records in total). One valid zero-change PR control remains in the
data but not on the logarithmic plot. The final outcome is
`COMPLETED_WITH_FAILURES`, not an all-successful hardware sweep.

| Curve | Adjacent measured 1x bracket, changed vertices (%) | Speedups at the bracket endpoints | Largest CPU-labeled fraction tested |
| --- | --- | --- | --- |
| AU SSSP | 0.21076--0.40017 | 1.132x / 0.777x | 38.93% |
| AU CC | 0.010286--0.100722 | 1.976x / 0.728x | 39.12% |
| AU ResPR | 0.013197--0.113336 | 1.069x / 0.504x | 14.30%; hardware overflow at this point |
| R19 SSSP | 0.100327--1.068878 | 3.259x / 0.314x | 52.61% |

The brackets use adjacent **targeted** median measurements, not an
interpolated or universal threshold. Ordinary batches appear as separate
open markers. For example, AU SSSP's ordinary 4096-update batch already
loses at 0.12382% changed vertices (0.317x), below its targeted crossing.
Update work, source distribution, propagation and current host handling
also affect latency; changed fraction alone does not determine performance.

| Artifact | Location |
| --- | --- |
| Combined plot | [PNG](handoff/figures/crossover.png), [vector PDF](handoff/figures/crossover.pdf) |
| One row per attempted point | [points.csv](handoff/data/points.csv) |
| Every warmup, formal sample and failed attempt | [samples.csv](handoff/data/samples.csv) |
| Exact curve data and brackets | [summary.json](handoff/data/summary.json) |
| Recorded outcome and file identities | [delivery.json](handoff/delivery.json) |
| Independent protocol/export check | [review.json](handoff/review.json) |
| Available round, work and timing fields | [work records](handoff/work/records.csv), [field semantics](handoff/work/summary.json) |
| Raw host logs and exact updates | [host-logs.tar.gz](handoff/data/host-logs.tar.gz), [updates.tar.gz](handoff/data/updates.tar.gz) |
| Python source, shared helpers, configs, scripts and tests | [crossover-source.zip](crossover-source.zip) |

The source archive is from commit `018b3c88` (full identity in
`handoff/source-bundle.json`). It is not a bundle of FPGA tools, graph data,
host executables or bitstreams: those remain explicitly hash-indexed in the
hardware/workload manifests. The earlier thirteen-point AU SSSP export is
preserved in [data/au-sssp/](data/au-sssp/summary.json), with its separate
[pilot preview](figures/au-sssp-crossover.png); use `handoff/` for this delivery.

The independent archive review passes for the 42 valid points and 126 formal
pairs; its PASS means the exported protocol and evidence agree, not that
the failed hardware points passed. The work export preserves 1356 available
timing/work records. Seventy-six focused tests pass across the crossover,
repository organization, memory guard and paired-host log parsers. No core,
SST or HLS implementation was changed or rebuilt for this study. The largest
recorded board-run cgroup peak was 8.58 GiB; no arm incurred an OOM event.

### Retained Hardware Failures

ResPR `fan-in-16384` (1.83143% changed) and `fan-in-131072` (14.30326%)
failed in the first Spine propagation round with `overflow=1`. The first
also reports `owner_status=6`; both reach FIFO occupancy 256. These are
**invalid latency points**, not slow successful runs or timeouts. Their logs
and input batches are retained, with no invented speedup. The intervening
`fan-in-65536` point at 7.20248% passes all paired checks (0.05284x), so a
single monotonic capacity limit based on changed fraction is not established.
This study reports the implementation failure; it does not claim to repair
the owner/reactivation scheduler or identify the precise RTL root cause.

Other retained attempts are a board-1 xclbin download timeout (`-110`) and
an initial PR host CLI mismatch, fixed before valid PR timings were obtained.
These are distinguished from the two workload-induced Spine failures.

## Predeclared Method

- Start with AU SSSP, then extend to representative graph classes and algorithms.
- Target affected fractions: 0.001%, 0.01%, 0.1%, 1%, 10%, 50%.
  Plot the achieved fraction; never relabel an unattainable target as measured.
- Also construct ordinary deterministic 8/64/512/4096-update batches.
- Freeze selection using CPU before/after results, without hardware timing.
- Both architectures start from the same converged old graph/state and run
  the same batch to the same convergence rule. Initial setup is excluded;
  host relaunch, final readback and in-window preparation remain included.
- One warmup pair and three measured pairs per point, alternating arm order.
  Retain every sample and failed attempt. Use ratio of median wall times.
- Record CPU changed counts, wall times, rounds, and available work/device
  counters. Missing counters stay missing, not inferred hardware readings.
- Use exclusive board leases, finite per-process memory/timeout bounds and
  the existing live memory guard. Never change machine-wide cache settings.

SSSP labels use exact integer Dijkstra on both old and new graphs. A second
incremental reference checks targeted batch construction. The denominator
includes all declared vertex IDs, including isolated IDs. Targeted batches
insert source shortcuts; ordinary batches use fixed-seed random
missing directed edges with weights 1--64. Existing topology and IDs are kept.
Some shortcuts make previously unreachable declared IDs, including isolated
IDs, reachable. Dense targeted cases are constructed stress workloads,
not claims about the frequency of such updates in the original trace.
Shortcut weights are selected from 1 and fractions of the old distance,
clamped to the weight12 ABI. This avoids forcing every nontrivial shortcut
to activate the same giant reachable region. Targeting uses a 10% count
tolerance, but plotted fractions are exact CPU counts.
The current maximum targeted batch is 131072 insertions (the shared host
update ceiling), not an unbounded synthetic dense rewrite.

CC labels use canonical minimum vertex IDs from independent before/after
union-find runs. A join is two reciprocal physical records; ordinary batches
of 8/64/512/4096 joins therefore contain 16/128/1024/8192 records.

Residual PR uses the current paired hosts' fixed direct per-vertex epsilon
`1e-6`, damping `0.85`, 128 FP32 old-rank rounds, and at most 256 thresholded
correction rounds. "Changed" means the final FP32 rank differs from its old
value, not merely a nonzero correction seed. The CPU oracle additionally
records changes above epsilon, initial active counts and propagated work.
High-degree-source and low-degree two-source fan-in candidates are both
retained. The latter deliberately stresses propagation on the existing
sink-free/self-loop-augmented input; it is not an ordinary-update distribution.
The primary PR sweep does not yet provide a second epsilon.

Candidate selection uses CPU impact only: nearest positive log-fraction for
each requested target, all four ordinary sizes, and one zero-propagation
control. Unreachable targets and zero-change points remain in the data;
zero cannot be plotted on the logarithmic x-axis. No extrapolated 50% point
is substituted for the achieved maximum. The AU SSSP pilot also motivates
an explicitly adaptive refinement at target fractions 0.2%, 0.4% and 0.6%;
these refine an observed sign-change interval, not the predeclared pilot.

## Code And Reproduction

The cohesive implementation is
`spine_cycle_sim/experiments/evaluation_impact/affected_fraction/`:
`sssp.py` and `cc.py` own integer CPU references; `pagerank_reference.cpp`
owns the FP32 reference. `prepare.py` / `pagerank.py` freeze workloads;
`select.py` selects PR points without hardware timings; `hardware.py` binds
existing hosts/images; `board.py` owns execution; `analyze.py` exports every
sample/failure and crossing brackets; `input_archive.py` preserves exact
updates without duplicating the old graph; `plot.py` renders with Matplotlib and
TX Typewriter, following the existing handoff typography. `delivery.py` waits
with a finite deadline and exports a complete or explicitly partial handoff;
retained failed attempts never masquerade as additional successful samples.
`review.py` independently checks the completed archive's point/sample coverage,
alternating order, raw-log digests, paired clocks, medians, CSV values and
recorded OOM events. This is a protocol/export check, not a new calibration.
`work.py` exports available log fields, including failed-arm diagnostics,
without inventing missing counters or treating layout slots as AXI bytes.

```sh
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.prepare \
  --graph /path/to/old-dynamic.graph --source 11 --dataset AU \
  --output /path/to/fresh-workload-directory
python3 -m unittest discover -s tests -p 'test_affected_fraction.py'
g++ -std=c++17 -O2 -ffp-contract=off -Wall -Wextra -Werror \
  spine_cycle_sim/experiments/evaluation_impact/affected_fraction/pagerank_reference.cpp \
  -o /path/to/pagerank_reference
```

Board runs require a finite systemd cgroup (8 GiB max / 6 GiB high for AU
SSSP and PR; 16 / 14 GiB for CC and R19 SSSP), zero swap and group OOM cleanup. The named
`zfs-arc-clean-half-background5-v1` policy retains the existing 32-GiB live
reserve and pressure checks. A waiting job is not a measured point.

```sh
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.board \
  --workloads /path/to/workloads.json --template /path/to/hardware.json \
  --comparator /path/to/compare_resident_fpga_logs.py --continue-on-case-error \
  --output /path/to/fresh-run
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.analyze \
  --campaign /path/to/run/campaign.json --output /path/to/fresh-export
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.plot \
  /path/to/fresh-export/summary.json /path/to/fresh-export/crossover
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.delivery \
  --campaign /path/to/run/campaign.json --hardware /path/to/hardware.json \
  --wait-seconds 14400 --output /path/to/fresh-handoff
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.review \
  /path/to/completed-handoff --output /path/to/completed-handoff/review.json
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.work \
  /path/to/completed-handoff --output /path/to/completed-handoff/work
```

Repeat `--campaign` for each primary campaign. Use `--retained-campaign` for
failed attempts that must be preserved but are superseded by primary reruns,
and `--candidate` for complete CPU candidate manifests. The delivery includes
CSV/JSON, exact updates, raw host logs, source/configuration identities, and
PNG/PDF. Continuations retain the original primary campaign and attempt only
its unattempted points; they do not overwrite failures. `COMPLETED` means all
planned points passed. `COMPLETED_WITH_FAILURES` means all unique planned
points were attempted but some failed, not that all timings are valid.
Missing/unattempted points produce `PARTIAL_RETAINED`. A waiting timeout
produces `WAIT_TIMEOUT` without exporting still-mutating campaigns.

The timing boundary is the current Fig. 7 boundary for each algorithm:
SSSP/PR use resident batch to final readback including host relaunch;
CC uses resident-old-graph host pack to final readback on both sides.
Do not compare an algorithm's absolute latency across these different scopes.
The PR hardware is matched at the existing derated 140-MHz clock;
SSSP and CC are at 150 MHz. These are measurements of the current hardware,
not proof that all target-only architecture features are implemented.

The portable export contains `points.csv`, every warmup/measured/failed
sample in `samples.csv`, full campaign and CPU workload manifests,
`host-logs.tar.gz` (including failed-arm logs and memory/clock receipts),
and `updates.tar.gz`. Each updates file contains exactly the four-field
insertion records, without a graph header. Reconstruct a dynamic graph with
the recorded old graph and its unchanged edge records, a `V E U` header,
then these updates. Large old graphs and bitstreams are hash-indexed rather
than duplicated in Git. The plotted x-coordinate is the CPU final-state
count divided by `V`, including declared isolated IDs. Available timing
fields are also exported in `samples.csv`; overlapping kernel durations
must not be summed or subtracted from wall and called pure host time.

Per-point paired-ratio minima/maxima and wall coefficients of variation
retain observed spread; neither is a confidence interval. Crossing brackets
refer to the tested targeted-workload family, not a universal threshold
determined by affected fraction alone. Ordinary batches are separate open
markers because their update count and source distribution also affect time.

## Local Run Index

Raw root: `/data/chuxiao/checks/affected-fraction-fpga-20261106`.

| Directory | Role |
| --- | --- |
| `inputs/sssp-au-v2`, `sssp-au-v2` | Predeclared ten-point AU SSSP pilot |
| `inputs/sssp-au-refine`, `sssp-au-refine` | Adaptive crossing refinement |
| `inputs/cc-au`, `cc-au-board0` | Reciprocal CC sweep on the working board |
| `inputs/respr-au`, `inputs/respr-au-fanin` | All CPU PR candidates, including zero spread |
| `inputs/respr-au-selected.json`, `respr-au-v2` | Primary PR sweep through the first retained overflow |
| `inputs/respr-au-remaining.json`, `respr-au-v3` | Unattempted PR points; continue after per-case failure |
| `inputs/sssp-r19`, `sssp-r19` | Second graph class: R-MAT, not a road network |
| `sssp-au-pilot-v1` | Superseded queued attempt; stopped before either arm started |
| `cc-au` | Board 1 xclbin-download timeout; no valid timing pair |
| `respr-au` | Superseded PR CLI failure; no valid timing pair |
| `partial-handoff-cli-v1`, `partial-handoff-pr-overflow-v2` | Earlier partial exports, retained outside Git |

The first SSSP CPU construction overshot intermediate targets; its inputs
are retained separately under `inputs/sssp-au`, not used as the v2 pilot.
The initial queued v1 board runner was explicitly stopped before execution
when v2 inputs replaced it; its last JSON status predates that termination.
The board-1 CC download failure is retained rather than interpreted as an
algorithmic loss. Subsequent campaigns use board 0 serially, with unchanged
paired binaries and clocks. Results and current completeness are reported
in the exported summary, not inferred from this directory list.

The combined export has six primary campaign journals covering 44 unique
planned points, plus two superseded failed attempts. The final completeness
and sample counts are recorded in `handoff/delivery.json` and independently
checked in `handoff/review.json`. Failed points never appear as successful
ratios in the plot. One zero-change PR control remains in the CSV/JSON but
cannot appear on the logarithmic x-axis.
