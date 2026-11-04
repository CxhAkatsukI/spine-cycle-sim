# Paired FPGA Checkpoint (2026-11-04)

Intermediate evidence, not a replacement for the Fig. 7-11 handoff. The
[independent stage check](../SSSP_STAGE_ADMISSION.md) passed weighted SSSP G
and the two matched Amazon R controls. The same image subsequently failed
the AskUbuntu R control. This is an image-specific checkpoint, not evidence
against a baseline that passed all R controls; it does not admit CC or ResPR.
The three Fig. 7 pairs and six Fig. 8 pairs below are single measurements;
there are no averages, projections, or substituted results.

## Fig. 7: Resident Update to Final Readback

Both arms start from the same old graph and converged state, take the same
eight updates, and are checked against the new-graph result. Wall time
includes host orchestration, intervening launches, and final readback,
but excludes initial graph preparation. The two arms used the same
driver-reported clocks in each reported pair.

| Dataset | Spine (ms) | G+R (ms) | G+R / Spine |
| --- | ---: | ---: | ---: |
| AU | 4.687 | 8.916 | 1.90 |
| SU | 4.221 | 11.156 | 2.64 |
| WK | 5.120 | 15.309 | 2.99 |

The [CSV](figure7.csv) retains all 24 requested rows; unmeasured rows have
no time or ratio. The [JSON](figure7.json) records input, executable/image,
clock, journal and comparator identities. The export was produced with
`python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.figure7_receipts`.

## Fig. 8: Initial Setup Plus One Update-Only Batch

Both arms construct and upload their own initial graph representation,
prepare the same batch, and run device maintenance through completion.
The sum excludes file parsing, image configuration, and correctness
readback. It includes no ReGraph propagation. This is a measured
initial-setup sensitivity, not the older modeled setup or the Fig. 7
resident window. A ratio above 1 favors Spine.

| Dataset | Updates | Spine (s) | G (s) | G / Spine |
| --- | ---: | ---: | ---: | ---: |
| AU | 64 | 1.927 | 0.818 | 0.425 |
| AU | 512 | 2.009 | 0.976 | 0.486 |
| AU | 4,096 | 1.949 | 0.771 | 0.395 |
| SU | 512 | 1.674 | 0.992 | 0.593 |
| WK | 512 | 1.813 | 1.873 | 1.033 |
| SO | 512 | 6.031 | No G timing | |
| PK | 512 | 18.763 | 37.381 | 1.992 |

AU/512 reuses a separately measured anchor; it was not measured twice.
The G arm on SO exhausted the lane-aware HBM metadata placement before
its timed update. It was not rerun with fewer metadata copies, and it has
no ratio. The [CSV](figure8.csv) separates update-call wall time from total
setup time. The [JSON](figure8.json) retains individual timers, input
hashes, clocks, oracles, and the failed case. The
[runner and input manifest](../FIGURE_IMPACT.md#figure-8-exact-inputs-for-a-native-g-check)
describe reproduction.

A [separate AU/64 host revision check](../FIGURE_IMPACT.md#au64-spine-host-revision)
reuses the same G arm and measures one changed Spine executable. It does
not overwrite the original pair above.

## Raw Evidence

The [archive](raw-board.tar.gz) contains the paired logs, captured states,
clock receipts, and the SO error. Paths in the JSON are absolute paths
from the original machine. The archive preserves the corresponding
directory suffixes. Its SHA-256 is
`1ae15c11445c2c6bc4921ca15921f8005b8e6c787c7eb13e6d86f9c4b61480fa`.

Fig. 9-11 are outside this checkpoint. See the
[figure impact audit](../FIGURE_IMPACT.md) for their separate evidence
and limitations.
