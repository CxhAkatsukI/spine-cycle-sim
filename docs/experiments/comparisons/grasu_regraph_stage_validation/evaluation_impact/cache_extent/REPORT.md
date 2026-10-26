# Revised FPGA Comparison: Review Summary

## Host Follow-Up In Progress

The [v2 host follow-up](fpga_results_v2/README.md) rebuilds Spine CC/ResPR
from the already existing optimized source, while retaining the exact six
bitstreams, workloads, thresholds and measured boundary. The independent AU
gate favors Spine by 3.764x for CC and 2.817x for zero-round ResPR. The full
24-case rerun and terminal review are not complete yet. Do not replace full
matrix rows with those gate measurements.

The results below are the completed, immutable **v1** campaign, which used
older CC/ResPR hosts and the optimized SSSP host. They remain evidence of
that configuration rather than the final performance of the optimized
CC/ResPR runtime. No paper or frozen package is overwritten.

## Decision And Scope

The **final 24-of-24 FPGA matrix passes its correctness gates**: eight full
graph workloads for each of SSSP, CC and ResPR. Every case has one excluded
warmup and three formal paired runs. Terminal raw-log verification, the
portable evidence archive, isolated reproduction and visual review pass.
Use the [delivery README](fpga_results_v1/README.md),
[figure preview](fpga_results_v1/figure/fpga_speedup.png),
[full data](fpga_results_v1/summary.csv) and
[review receipt](fpga_results_v1/review/README.md).

The actual board results do **not** show a universal Spine win. SSSP favors
Spine on eight of eight graphs. CC favors Spine on four and G+R on four.
ResPR also favors Spine on four and G+R on four.
All eight ResPR cases have zero propagation rounds on both implementations;
they measure update/correction/completion, not iterative PR propagation.

## Measured Speedups

Values are `median G+R wall / median Spine wall`: above one favors Spine;
below one favors G+R. No frequency normalization, fitted timing adjustment
or outlier removal is applied. There are no missing, projected or timeout rows.

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

The table is rounded for reading. The final CSV retains exact wall medians,
ratios, actual clocks and all formal propagation counts. Raw samples, matrix,
plan and file-hash index are in the package's `raw_evidence.tar.gz`, under
`evidence/`. Earlier partial checkpoints remain historical evidence.

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

## Evidence And Final Checks

Machine-local evidence root:
`/data/chuxiao/builds/grasu-cache-extent-20261025`.

| Evidence under that root | What it proves |
| --- | --- |
| `source-zfs-v3/`, `hls-zfs-v3/` | Source-functional and exported-interface gates; not board timing |
| `route-zfs-v2/{sssp,cc,respr}/` | Revised artifacts, actual clocks and route evidence |
| `matrix-inputs-zfs-v3/plan.json` | Frozen 24-case workload, boundary, repetition and identity contract |
| `matrix-zfs-v3/` | Terminal `FPGA_MATRIX_PASS`, all 24 cases and 96 paired runs, resource records and raw logs |
| `terminal-delivery-v1/evidence/` | Final reparse of all 96 paired runs, source/binary/input pins, correctness, medians, actual clocks and memory containment |
| `terminal-delivery-v1/profile/` | All 72 formal G+R event profiles and 48 architecture/case wall-statistic records; not exclusive stage attribution |
| `terminal-tool-preflight-v2/` | 37 delivery/plot/profile tests, including real font rendering; synthetic fixtures are not board results |
| `final-roundtrip-review-v2/` | Independent extraction of all 615 archived records and isolated reproduction; byte-identical PNG/CSV and equivalent PDF, with embedded txtt |

The [portable supporting package](implementation_evidence/README.md) includes
127 hash-verified records (7.5 MiB), with 16 retained failed stage outcomes.
It makes implementation checks reviewable without copying bitstreams or
build trees. The separate [final FPGA package](fpga_results_v1/README.md)
adds a 3.3-MiB board archive (615 hash-verified records), all measured data,
the Python figure/profile code, PNG/PDF output and the review receipt.

All 24 saved case resource records have zero `high`, `max`, `oom`,
`oom_kill` and `oom_group_kill` events. Runs used finite 16/24/32-GiB hard
caps, zero swap and a 24-GiB admission reserve. On this ZFS host, admission
uses Linux `MemAvailable` plus bounded evictable ARC data, not `MemFree`.
It neither adds all cached memory nor changes ZFS parameters.

The initial PDF byte-equality check failed because of a randomized font
subset name. That attempt is retained. The revised check allows only that
name change, requires all other decompressed PDF bytes to agree, and also
requires byte-identical 300-dpi raster output. No measurements or renderer
code were altered. See the review receipt for commands and hashes.

For commands, source ownership, memory accounting and retained failures, use
the [technical runbook](RUNBOOK.md). The [study index](README.md) is the short
navigation entry point.
