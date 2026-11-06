# Affected-Fraction FPGA Crossover

This experiment varies the **actual fraction of final vertex values changed**,
not batch size or the initial active set, and measures G+R / Spine resident
wall latency. It supplements, and does not replace, the frozen Figures 7--11.
The paper is not edited. Raw evidence is retained outside the checkout;
completed measurements are exported here with their input and host-log archives.

## Measured AU SSSP Pilot

All thirteen pilot/refinement points completed one warmup and three measured
pairs, with both arms passing their CPU correctness checks at matched clocks.
These are FPGA wall measurements, not simulator predictions. The remaining
AU CC, AU ResPR and R19 SSSP campaigns are still running or queued; they are
not represented as completed measurements here.

| Actual changed fraction | Batch records | G+R wall (ms) | Spine wall (ms) | G+R / Spine |
| --- | ---: | ---: | ---: | ---: |
| 0.00116% | 3 | 12.016 | 5.810 | 2.068 |
| 0.01029% | 7 | 22.781 | 12.268 | 1.857 |
| 0.10014% | 304 | 30.708 | 20.519 | 1.497 |
| 0.21076% | 190 | 30.972 | 27.364 | 1.132 |
| 0.40017% | 59 | 33.928 | 43.638 | 0.777 |
| 0.60200% | 78 | 33.904 | 56.286 | 0.602 |
| 1.00198% | 78 | 40.472 | 88.365 | 0.458 |
| 10.22491% | 1740 | 56.936 | 951.272 | 0.060 |
| 38.93487% | 131072 | 44.838 | 2416.030 | 0.019 |

For this targeted shortcut family, adjacent measurements bracket the 1x
crossing between **0.21076% and 0.40017%** affected vertices. This is an
empirical bracket, not an interpolated or universal threshold. Ordinary
8/64/512/4096-update batches respectively achieve 2.286/2.454/1.286/0.317x
at 0.000582/0.001553/0.014167/0.123816% changed vertices. The last point
loses despite a lower changed fraction: batch-update work and source/work
distribution also matter. All losses remain in the exported data and plot.

The completed AU data are in [data/au-sssp/summary.json](data/au-sssp/summary.json),
[points.csv](data/au-sssp/points.csv), and [samples.csv](data/au-sssp/samples.csv).
This export contains 13 measured points and all 52 pairs, including 13 excluded
warmups. The [PNG preview](figures/au-sssp-crossover.png) and
[vector PDF](figures/au-sssp-crossover.pdf) are generated solely from that export.

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
SSSP and PR; 16 / 14 GiB for CC), zero swap and group OOM cleanup. The named
`zfs-arc-clean-half-background5-v1` policy retains the existing 32-GiB live
reserve and pressure checks. A waiting job is not a measured point.

```sh
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.board \
  --workloads /path/to/workloads.json --template /path/to/hardware.json \
  --comparator /path/to/compare_resident_fpga_logs.py --output /path/to/fresh-run
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.analyze \
  --campaign /path/to/run/campaign.json --output /path/to/fresh-export
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.plot \
  /path/to/fresh-export/summary.json /path/to/fresh-export/crossover
python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.delivery \
  --campaign /path/to/run/campaign.json --hardware /path/to/hardware.json \
  --wait-seconds 14400 --output /path/to/fresh-handoff
```

Repeat `--campaign` for each primary campaign. Use `--retained-campaign` for
failed attempts that must be preserved but are superseded by primary reruns,
and `--candidate` for complete CPU candidate manifests. The delivery includes
CSV/JSON, exact updates, raw host logs, source/configuration identities, and
PNG/PDF. `COMPLETED` requires every planned point; failed primary campaigns
produce `PARTIAL_RETAINED`. A waiting timeout produces `WAIT_TIMEOUT` without
exporting still-mutating campaigns.

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
| `inputs/respr-au-selected.json`, `respr-au` | CPU-selected primary PR hardware sweep |
| `inputs/sssp-r19` | Second graph class: R-MAT, not a road network |
| `sssp-au-pilot-v1` | Superseded queued attempt; stopped before either arm started |
| `cc-au` | Board 1 xclbin-download timeout; no valid timing pair |

The first SSSP CPU construction overshot intermediate targets; its inputs
are retained separately under `inputs/sssp-au`, not used as the v2 pilot.
The initial queued v1 board runner was explicitly stopped before execution
when v2 inputs replaced it; its last JSON status predates that termination.
The board-1 CC download failure is retained rather than interpreted as an
algorithmic loss. Subsequent campaigns use board 0 serially, with unchanged
paired binaries and clocks. Results and current completeness are reported
in the exported summary, not inferred from this directory list.

The bounded `spine-impact-delivery-20261106-v2.service` waits for the five primary
campaigns (44 planned points total) and exports to `handoff/` in this folder.
That future output is not a completed delivery until `delivery.json` says so.
Current jobs can be inspected without attaching to a long-running command:

```sh
systemctl --user status spine-impact-r19-sssp-20261106.service \
  spine-impact-au-cc-board0-20261106.service \
  spine-impact-au-pr-20261106.service spine-impact-delivery-20261106-v2.service
```
