# Resident SSSP Follow-Up (2026-11-04)

This single-pass FPGA checkpoint adds R19, PK and SO to the
[first three measured SSSP pairs](../paired-board-checkpoint/README.md).
The exact G+R image passed independent G and both Amazon R controls.
It later failed the [AskUbuntu topology control](../SSSP_STAGE_ADMISSION.md#askubuntu-topology-control)
by exceeding the 15% overhead limit. These resident pairs remain
measurements of that image, not evidence against a baseline that passed
all R controls. They do not admit CC or ResPR.

| Dataset | Spine (ms) | G+R (ms) | G+R / Spine |
| --- | ---: | ---: | ---: |
| AU | 4.687 | 8.916 | 1.90 |
| SU | 4.221 | 11.156 | 2.64 |
| WK | 5.120 | 15.309 | 2.99 |
| SO | 15.470 | 221.491 | 14.32 |
| R19 | 4.157 | 30.913 | 7.44 |
| PK | 8.306 | 107.197 | 12.91 |

SO, R19 and PK each used eight identical weighted inserts within the pair.
SO took one round on each arm; R19 and PK took two. Both arms started from the same old-graph
converged state. Both results passed the correctness checks and the
paired clocks matched. The wall-time window starts with the batch
resident and ends after final readback, including timed host
orchestration and relaunch. Each arm was timed once without warmups.
SO's cgroup peaked at 19.08 GiB, with no `memory.high`, limit or OOM
events. Its G update span was 12.028 ms, below the complete Spine wall
time, so SO is not included in the [zero-R bound](../FIGURE_IMPACT.md#figure-7-r-only-bound-on-two-new-sssp-pairs).

The original AU/SU/WK receipts were imported without executing those
arms again. The continuation pins the stopped predecessor journal and
refuses to replay a case that already attempted a board arm. The
[live queue and reproduction command](../FIGURE_IMPACT.md#figure-7-receipt-export)
explain how to make a later snapshot.

The [CSV](figure7.csv) and [JSON](figure7.json) preserve all 24 requested
rows, with blank timings for rows not admitted at the snapshot. The
[PK/R19 archive](raw-sssp-followup.tar.gz) and [SO archive](raw-so.tar.gz)
include the logs, clock evidence, G+R result state and case receipts.
Original AU/SU/WK logs are in the previous checkpoint. Absolute paths in
the JSON refer to the acquisition host.

| Archive | SHA-256 |
| --- | --- |
| PK/R19 | `70974da103d6e9852814d5a75eaab52e1cfc277e5551fff601470e97db365a4c` |
| SO | `d78663852336fb9fc8ec0279285750879050415d6c3f9a6dafd5f72b469838fe` |

This is not a replacement for the Figure 7-11 handoff. It neither assigns
the measured R gap to untested datasets nor uses the R result to certify
other figures.
