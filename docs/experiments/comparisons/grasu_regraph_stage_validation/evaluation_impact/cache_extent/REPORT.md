# Revised FPGA Comparison: Review Summary

## Current V2 Decision

The [v2 host follow-up](fpga_results_v2/README.md) is complete: all 24 cases
and 96 paired runs pass correctness, provenance and memory checks. Raw-log
reparsing, isolated reproduction and visual review pass. **Spine is faster
on all eight measured graphs for each algorithm.** Use the
[current preview](fpga_results_v2/figure/fpga_speedup.png),
[exact data](fpga_results_v2/summary.csv),
[old/new medians](fpga_results_v2/comparison.csv) and
[review receipt](fpga_results_v2/review/README.md).

Values below are `median G+R wall / median Spine wall`, using three formal
pairs after one excluded warmup. All samples remain; no timing fit or
frequency normalization is applied.

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

Ranges are SSSP 4.36--96.48x, CC 3.87--78.63x and ResPR 1.49--5.59x.
**All frozen ResPR cases require zero propagation rounds on both systems
and their CPU oracles.** These are update/correction/completion speedups,
not evidence for iterative PR propagation. Formal SSSP and CC round counts
match between systems and are preserved in the CSV.

### What Changed From V1

The v1 campaign used the optimized Spine SSSP executable but older CC/ResPR
hosts. V2 builds those two specializations from the already existing clean
optimized source, commit `cb42376663c534f0bd0c25d271737ca34893135e`. It changes
no HLS source or bitstream. Scratch residency avoids an implicit first-use
upload of an unused 512-MiB host active-record buffer; the device writes
consumed counted prefixes before use. The runtime also avoids clearing
unused active-array tails and copying the full unchanged 44-MiB metadata.
Host correction, active publication, consistency checks, relaunch and final
readback remain in their original paths and timed window. This does not
introduce a new autonomous kernel.

The exact six bitstreams, workloads, batches, thresholds, clocks, formal
propagation counts and resident boundary are unchanged. The boundary includes
host launch/wait, inter-round relaunch and final readback, but excludes initial
graph/PMA preparation, residency, old-state preload, batch preparation/upload
and CPU oracles on both sides. It is not whole-startup latency.

Spine CC AU changes from 82.3447 to 3.05053 ms, and WK from 132.312 to
7.54539 ms; unchanged G+R CC medians vary by at most 1.3%. These independently
collected campaigns are not a simultaneous controlled A/B test of every
optimization. SSSP's executable is unchanged, so its measured variations
are not attributed to code changes. All raw samples are retained.

### Current Evidence And Limits

The machine-local v2 root is
`/data/chuxiao/checks/spine-cc-respr-host-20261026`. `full-matrix-v2/` is the
terminal passing matrix. `full-matrix-v1/` retains a pre-board pin-schema
admission failure; no board sample ran in that attempt. The portable archive
contains 638 hash-verified files, including all paired logs, frozen plans,
source/build receipts and the old/new contract comparison. The unchanged
Python renderer and profile analyzer reproduce outside the checkouts.

All 24 saved case memory-event records have zero `high`, `max`, `oom`,
`oom_kill` and `oom_group_kill` events, under finite 16/24/32-GiB hard limits,
zero swap and a 24-GiB admission reserve. The independent 2-GiB-capped
reproduction peaked at 124.8 MiB. No paper or frozen figure is overwritten.

This remains a resident FPGA comparison, not new simulator calibration or
original-publication matching. ResPR's actual G+R DATA 149/HBM 432-MHz and
Spine DATA 150/HBM 448-MHz clocks remain disclosed. Event unions do not
isolate exclusive internal stages, and wall minus event union is not pure
host time. The approximately 2.47x original-R publication-scale ratio remains
a separate limitation. See the v2 README for the complete contract.

## Historical V1 Decision And Scope

Everything below this heading describes the immutable v1 campaign, not the
current v2 performance. Its older CC/ResPR hosts produced the losses recorded
below. The original data and conclusions are retained rather than rewritten.

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

## Historical V1 Speedups

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

## V1 Comparison Contract

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

## V1 Implementation Checks

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

## V1 Limitations

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

## V1 Evidence And Checks

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
