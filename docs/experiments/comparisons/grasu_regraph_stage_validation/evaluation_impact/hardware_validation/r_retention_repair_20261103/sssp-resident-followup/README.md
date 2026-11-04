# Resident SSSP Follow-Up (2026-11-04)

This single-pass FPGA checkpoint adds R19 and PK to the
[first three measured SSSP pairs](../paired-board-checkpoint/README.md).
The exact G+R image passed the [independent G and weighted R gates](../SSSP_STAGE_ADMISSION.md).
That admission does not extend to CC or ResPR.

| Dataset | Spine (ms) | G+R (ms) | G+R / Spine |
| --- | ---: | ---: | ---: |
| AU | 4.687 | 8.916 | 1.90 |
| SU | 4.221 | 11.156 | 2.64 |
| WK | 5.120 | 15.309 | 2.99 |
| R19 | 4.157 | 30.913 | 7.44 |
| PK | 8.306 | 107.197 | 12.91 |

R19 and PK each used eight identical weighted inserts and took two
rounds to converge on each arm, starting from the same old-graph
converged state. Both results passed the correctness checks and the
paired clocks matched. The wall-time window starts with the batch
resident and ends after final readback, including timed host
orchestration and relaunch. Each arm was timed once without warmups.

The original AU/SU/WK receipts were imported without executing those
arms again. The continuation pins the stopped predecessor journal and
refuses to replay a case that already attempted a board arm. The
[live queue and reproduction command](../FIGURE_IMPACT.md#figure-7-receipt-export)
explain how to make a later snapshot.

The [CSV](figure7.csv) and [JSON](figure7.json) preserve all 24 requested
rows, with blank timings for rows not admitted at the snapshot. The
[raw archive](raw-sssp-followup.tar.gz) includes logs, clock evidence and
case receipts for R19 and PK; original AU/SU/WK logs are in the previous
checkpoint. Absolute paths in the JSON refer to the acquisition host.
The archive SHA-256 is
`70974da103d6e9852814d5a75eaab52e1cfc277e5551fff601470e97db365a4c`.

This is not a replacement for the Figure 7-11 handoff. It neither assigns
the measured R gap to untested datasets nor uses the R result to certify
other figures.
