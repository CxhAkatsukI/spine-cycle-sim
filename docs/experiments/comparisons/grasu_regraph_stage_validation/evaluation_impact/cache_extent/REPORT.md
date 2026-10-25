# Revised FPGA Comparison: Review Summary

## Decision And Scope

This is a **21-of-24 checkpoint, not the final matrix**. All eight SSSP and
all eight CC comparisons pass; five ResPR comparisons pass. ResPR LJ, LJ08
and R19 are not yet admitted. The remaining measurements, terminal evidence
package, rendered figure review and final push are still required.

The actual board results do **not** show a universal Spine win. SSSP favors
Spine on eight of eight graphs. CC favors Spine on four and G+R on four.
Of the five admitted ResPR cases, two favor Spine and three favor G+R.
All five ResPR cases have zero propagation rounds on both implementations;
they measure update/correction/completion, not iterative PR propagation.

## Measured Speedups

Values are `median G+R wall / median Spine wall`: above one favors Spine;
below one favors G+R. No frequency normalization, fitted timing adjustment
or outlier removal is applied. A dash means unfinished, not zero or timeout.

| Graph | SSSP | CC | ResPR |
| --- | ---: | ---: | ---: |
| AU | 4.304 | 0.144 | 0.398 |
| SU | 6.386 | 0.185 | 0.517 |
| WK | 6.075 | 0.570 | 0.819 |
| SO | 41.697 | 7.308 | 4.482 |
| PK | 75.332 | 3.407 | 2.154 |
| LJ | 89.168 | 10.007 | - |
| LJ08 | 90.575 | 9.207 | - |
| R19 | 19.387 | 0.838 | - |

The table is rounded for reading. Its authoritative checkpoint is
`independent-pair-audit-v20/matrix-checkpoint.json` below, not a replacement
CSV for an unfinished matrix. That snapshot contains all 24 declared rows,
including the three unfinished rows.

## Comparison Contract

- Both systems start from the same frozen old-graph converged state, apply
  the same batch and satisfy the same final correctness/convergence gate.
- Each case has one excluded warmup and three formal paired repetitions,
  alternating execution order. The ratio uses the two formal wall medians.
- The resident interval includes updates, propagation when required, host
  launch/wait, inter-round relaunch and final readback. Initial graph/PMA
  preparation, initial residency, batch preparation/upload and CPU validation
  are excluded on both sides. This is not whole-startup latency.
- The batch has eight edits. CC encodes eight undirected insertions as
  sixteen reciprocal directed records; SSSP and ResPR have eight records.
- ResPR uses direct per-vertex epsilon `1e-6`, alpha `0.85`, and sink-completed
  frozen inputs. It does not divide epsilon by the vertex count. Those inputs
  are transformed workloads, not unmodified directed datasets.
- SSSP/CC data clocks are 150 MHz on both systems. ResPR G+R uses DATA
  149/HBM 432 MHz and Spine uses DATA 150/HBM 448 MHz after automatic scaling.
  The raw measured walls are retained despite these differences.
- The frozen native G+R hosts use GCC 15.2 `-O2`; Spine uses GCC 15.2 `-O3`.
  The tiny SSSP source-active preparation is outside G+R's interval but inside
  Spine's device path. This asymmetry is disclosed, not corrected by subtraction.

## What Was Fixed And Verified

The shared G+R host helper explicitly establishes initial input residency
before updates. A final cache-extent argument then limits GraSU preload and
writeback to each PMA half's valid span, rounded to sixteen banks. The cache
remains sixteen URAM banks and 131072 words; every required word is still
transferred on every invocation. No cross-launch persistence is assumed.

The opt-in simulator path derives the same span and conserves rounded
read/write traffic. Source oracles, HLS interface checks, the fresh 31-target
core regression, and separate bounded-cache SST functional tests pass.
These establish implementation/state/traffic checks, **not new FPGA timing
calibration or original-publication performance reproduction**.

All three revised G+R xclbins exist. SSSP and CC pass final route timing;
ResPR was automatically clock-scaled and its reduced clocks remain visible.
Spine ResPR's successful route was independently audited after a dependency
postprocessing failure; that failed wrapper result was preserved. Its AU
smoke is distinct from the subsequent paired matrix samples.

## Important Limitations

- CC losses are real measurements from the frozen current Spine CC host,
  not silently replaced by the separately optimized SSSP host. Aggregate
  timings cannot attribute the whole wall gap to one host function.
- SSSP SO's three Spine walls are 15.508, 18.0336 and 73.8605 ms. All remain
  in the evidence; the population CV is 75.23%. The cause is not established.
- Zero-round ResPR comparisons do not demonstrate iterative propagation
  performance, however large or small their speedup ratios.
- ReGraph's approximately 2.47x publication-number ratio is an accepted
  limitation, not a controlled reproduction error or a successful match.
  The [original-R control](../../../grasu_regraph_publication_match/board_probe/dense_partitions.md)
  has different publication-equivalence questions from this dynamic matrix.
- Event unions and resident wall time do not isolate every internal stage.
  Their difference is not pure host time, and this study does not calibrate
  the paper's stage-breakdown figure or replace any paper data.

## Evidence And Remaining Delivery Gates

Machine-local evidence root:
`/data/chuxiao/builds/grasu-cache-extent-20261025`.

| Evidence under that root | What it proves |
| --- | --- |
| `source-zfs-v3/`, `hls-zfs-v3/` | Source-functional and exported-interface gates; not board timing |
| `route-zfs-v2/{sssp,cc,respr}/` | Revised artifacts, actual clocks and route evidence |
| `matrix-inputs-zfs-v3/plan.json` | Frozen 24-case workload, boundary, repetition and identity contract |
| `matrix-zfs-v3/` | Actual paired raw logs, resource records, manifests and current matrix state |
| `independent-pair-audit-v20/` | Independent reparse of 84 paired executions across 21 cases and 1553 unique pinned files |
| `profile-checkpoint-21-v1.log` | Reparse of 63 formal G+R profiles and 42 wall-statistic records; not exclusive stage attribution |
| `terminal-tool-preflight-v2/` | 37 delivery/plot/profile tests, including real font rendering; synthetic fixtures are not board results |

The terminal finalizer is waiting for the actual matrix. A final release
still requires all 24 terminal decisions, raw-log revalidation of every
admitted pair, a portable evidence package, inspection of the measured plot,
updated machine-readable data, repository checks and a verified remote push.
No queued job or successful packaging test substitutes for those gates.

For commands, source ownership, memory accounting and retained failures, use
the [detailed study guide](README.md).
