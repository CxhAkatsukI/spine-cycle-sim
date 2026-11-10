# RN follow-up experiments

RN means the full SNAP roadNet-CA graph, not R19 or a compact road slice.
This note tracks the November 10 manuscript snapshot. The paper is unchanged.

[FPGA sweep data](followup/rn_fpga_sweep.csv) ·
[Ligra timings](followup/rn_ligra_trifoliate.csv) ·
[Inputs and CPU receipts](followup/workloads_and_ligra.tar.gz)

| Experiment | RN scope | Evidence required |
| --- | --- | --- |
| Fig. 7, headline dynamic latency | SSSP, CC, ResPR on the full graph | Paired FPGA wall times from the resident old state through checked final readback; one sample per arm in this supplement |
| Batch size and update impact | RN is the high-diameter graph; ordinary 8, 64, 512 and 4,096 insertions; separately vary affected fraction | Matched paired timing, actual changed vertices, updated sources, propagation work and correctness. Report the measured extent; do not extrapolate a crossover. |
| Comparison with dynamic designs | The draft explicitly says all nine graphs | Ligra-compatible timings for the three headline algorithms and four batch sizes are measured on Trifoliate (EPYC 7C13, eight pinned threads), not on the manuscript's EPYC 9755. The D-ACTS model is not timing-qualified; a matched FPGA Host-CSR run and H200 Gunrock run are not in this delivery. |
| Widest path | The draft says every graph used for SSSP; its RN table row lists only SSSP/CC/ResPR | Include RN if the all-SSSP-graphs claim is retained. No qualified widest-path pair was found in the selected handoff. |
| Deletions and sustained operation | The draft does not name RN for the deletion-fraction or sustained sweeps; the timestamped panel explicitly uses signed KONECT traces | RN is a static SNAP road graph, not a signed history. A separate synthetic RN replay would be a different experiment. |
| Selected Figs. 8-11 | No RN requirement in the frozen figure definitions | Fig. 8 is the five-dataset/AU throughput sweep, Fig. 9 is AU/SU/WK, and Figs. 10-11 use their own stage cases and frozen fit/holdout split. Do not add RN to those populations silently. |

The existing [crossover package](../affected_fraction_fpga_20261107/README.md)
does not have an RN curve. Its R19 series is synthetic. For the RN ordinary
sweep, `prepare_batch_sweep.py` reuses the Fig. 7 input at 8 and extends it
with a seeded stream of absent edges between real SNAP vertices. Each larger
batch is a prefix of that stream plus the Fig. 7 records. CC applies two
reciprocal records per logical insertion. The denominator is the 1,965,206
real vertices rather than the padded ID space. These rules differ from the
earlier independent crossover batches and should be stated when comparing
curves.

The controlled SSSP inputs each insert one weighted shortcut. The CPU
candidate search selects by changed vertices alone, with no timing feedback.
An independent full Dijkstra run verifies the affected count. Six points
actually change 18, 179, 1,682, 10,972, 202,544, and 997,504 vertices.
Their results should be plotted by actual changed fraction, not by the
target bin or alongside the ordinary sweep as if the batches were drawn
from the same distribution.

`MEASURED` in the FPGA CSV means both arms passed their final reference
checks. Each row uses one measured pair; the ordinary 8-update rows
reuse the Fig. 7 measurements. Blank timing and counter fields indicate
missing observations, not zeros. Spine's SSSP work counters count visits
and requests, not unique edges or distinct sources. The Ligra timings
include CPU CSR rebuild and incremental propagation but exclude old-state
preparation and reference validation. They are local comparison data,
not a substitute for the manuscript's cross-platform result.
