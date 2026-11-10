# RN follow-up experiments

RN means the full SNAP roadNet-CA graph, not R19 or a compact road slice.
This note tracks the November 10 manuscript snapshot. The paper is unchanged.

[FPGA sweep data](followup/rn_fpga_sweep.csv) ·
[Reported FPGA timing fields](followup/rn_fpga_timing_records.csv) ·
[Measured crossing brackets](followup/rn_impact_summary.json) ·
[Affected-fraction preview](followup/rn_affected_fraction.png) ·
[Batch-size preview](followup/rn_batch_size.png) ·
[Ligra timings](followup/rn_ligra_trifoliate.csv) ·
[Inputs and CPU receipts](followup/workloads_and_ligra.tar.gz)

## Measured Results

This snapshot contains 14 validated pairs out of 18 planned. The last
controlled point and three larger ordinary SSSP points are not yet in
the previews. CC and ResPR have all four ordinary points.

On the controlled one-edge SSSP sweep, Spine is 2.05x faster at
10,972 changed vertices (0.558%). G+R is 5.08x faster at 202,544 changed
vertices (10.31%). These adjacent measured points bracket a change
of winner, not a measured or universal crossover fraction.

For CC, the largest old component already has minimum label zero and
contains 1,957,027 of 1,965,206 real vertices. In an insertion-only
experiment its labels cannot change. At most 8,179 real vertices
(0.416%) can change labels. The 4,096-insertion point measures 774.46 ms
on Spine and 788.47 ms on G+R, approximately parity for one pair.
In all four ordinary ResPR pairs, both arms have zero nonempty
propagation rounds at the fixed epsilon of 1e-6. These points do not
establish the ResPR crossover.

## Scope

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
and requests, not unique edges or distinct sources. CC reports relaxation
edge visits and row queries in its own fields. G+R reports the layout's slot
count per execution, not measured edge reads or bytes. The Ligra timings
include CPU CSR rebuild and incremental propagation but exclude old-state
preparation and reference validation. They are local comparison data,
not a substitute for the manuscript's cross-platform result.

The timing-field CSV reports each host log's named fields as emitted.
Concurrent kernel events can overlap and some counters exclude maintenance
or preparation; do not sum these fields or subtract their sum from wall
time to infer host overhead.

## Reproduce

Run from the simulator repository root, after generating the three RN graphs
and compiling the two reference programs in [the Fig. 7 guide](README.md#reproduce).
Use unused output directories.

```sh
export PYTHONPATH="$PWD"
for algorithm in weighted_sssp connected_components residual_pagerank; do
  python3 "$handoff/prepare_batch_sweep.py" \
    "$scratch/rn-inputs/$algorithm/workloads.json" "$scratch/rn-sweep/$algorithm" \
    "$scratch/check_old_state" "$scratch/pagerank_reference"
done
python3 "$handoff/prepare_batch_sweep.py" \
  "$scratch/rn-inputs/weighted_sssp/workloads.json" "$scratch/rn-sweep/sssp-control" \
  "$scratch/check_old_state" "$scratch/pagerank_reference" --controlled-sssp
```

Use the same board command and hardware bindings as in the Fig. 7 guide,
with input `$scratch/rn-sweep/$series/workloads.json` and output
`$scratch/board-sweep-$series`. The ordinary campaigns pass
`--point ordinary-64 --point ordinary-512 --point ordinary-4096` to reuse
the measured Fig. 7 points rather than rerun them; the `sssp-control` campaign
uses the weighted SSSP binding and all six points. Add
`--continue-on-case-error --timeout-seconds 1800` to retain a failed point
without ending its series. Do not skip failed points when reporting coverage.

The collector expects the original scratch layout: the three Fig. 7
campaign names in `collect_followups.py`, the four follow-up series above,
and the archived `ligra/` receipts. Regenerate tables and preserve the
completed follow-up board logs with:

```sh
python3 "$handoff/collect_followups.py" "$scratch" /tmp/rn-tables --archive-logs
python3 "$handoff/render_followups.py" /tmp/rn-tables
```

The renderer uses the selected handoff's GraphyFlow-based Matplotlib style
and TX Typewriter. It needs LaTeX `txfonts` and `pdftoppm` for the PNG preview.
The affected-fraction chart uses a linear interval from 0% to 0.001%
and a log scale above it, so zero-change observations remain at exactly
0%. Only controlled SSSP points are connected; the ordinary batches and
controlled shortcuts are separate populations.
