# Figure Dependency Audit

## Figure 7 Receipt Export

From the simulator repository, use the live campaign's six journals to
produce a new, immutable-by-convention evidence snapshot. Run this offline;
it does not launch FPGA jobs or modify existing packages.

```bash
run=/data/chuxiao/checks/source-retention-repair-20261104
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.figure7_receipts \
  --sssp-matrix "$run/sssp-singlepass-matrix-v1/matrix.json" \
  --sssp-au "$run/sssp-resident-au-v2/queue.json" \
  --cc-matrix "$run/cc-singlepass-matrix-v1/matrix.json" \
  --cc-r19 "$run/cc-r19-resident-wall-v1/queue.json" \
  --respr-matrix "$run/respr-matrix-v1/results.json" \
  --respr-screen "$run/resident-joint-board-v2/results.json" \
  --output "$run/figure7-receipt-snapshot.json"
```

The export has eight rows each for SSSP, CC, and ResPR. FullPR is outside
this campaign. No ratios are emitted for pending or failed rows. If a live
journal changes during export, rerun rather than mixing snapshots. Admitted
rows reference the original logs, verified clock
receipts, image identities, wall-time comparison, and independent G and R
ratios. It indexes existing correctness/stage admission; it does not rerun
the correctness oracles or establish results for figures 8--11. CC starts
at host pack; SSSP and ResPR start at a resident batch. ResPR rows report
whether both arms performed propagation. Do not pool these scopes or
interpret a correction-only result as propagation evidence.

This is a replay of the [frozen November 3 handoff](../../figure7_11_handoff_20261103/README.md),
not new measurements or an admission decision. A ratio from the two R controls
cannot be applied as a correction factor to other graphs, algorithms, or
total resident latency. The controls measure a single gather/apply execution;
the Figure 7 comparisons include the actual update and convergence path.

| Figure | What the directory-span repair can affect | Evidence needed before reuse |
| --- | --- | --- |
| 7, SSSP/CC | All 16 timed G+R runs execute the adapter: SSSP has 1--3 supersteps, CC 1--2. | Retest on the admitted algorithm-specific images unless a matched, measured bound establishes the claimed advantage. |
| 7, ResPR | All eight timed G+R runs execute one full correction pipeline. Neither arm takes a later propagation round on these batches. | Retest after R admission; explicitly keep these eight results separate from nonempty propagation. |
| 8 | No R execution in the update-only boundary. Its G configuration is nevertheless older than the cached/replicated hardware G. | Do not rerun because of R alone. To call it a comparison against current G, regenerate or demonstrate equivalence of the G device, host and transfer inputs. It remains one batch, not ten. |
| 9 | It uses simulated G+R and Spine requests. Identical adapter outputs do not establish identical accepted requests, request order, or background HBM energy. | Verify the current implementation's request ledger against the intended simulator profile; rerun affected simulator pairs for a refreshed comparison. Preserve the modeled energy scope. |
| 10/11 | Spine-only stage attribution and a fit to Spine simulator outputs; neither consumes R measurements. | Retain as predictions for the exact frozen Spine model. Re-execute/refit only if a relevant Spine model or workload changes. R admission does not calibrate them. |

## Figure 8: Exact Inputs For A Native G Check

The independent G gate uses AU with 131,072 inserts and measures the
device update event span. It cannot stand in for Figure 8: the latter uses
AU at 64, 512, and 4,096 updates and SU/WK/SO/PK at 512, and includes
preparation and upload. Its frozen arm table records the row counts and the
case directory; `config.json` in that directory names the two raw slices.
For example, prepare the exact AU 512-update row from the simulator checkout:

```bash
input=/data/tmp/chuxiao/large_graph_campaign_v1/workloads/sx_askubuntu
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.figure8_inputs \
  "$input/graphs/directed_weighted.slice" \
  "$input/updates/directed/insert_u512.slice" \
  /tmp/au_fig8_u512.graph --vertices 515281 --edges 390847 --batch-size 512
```

The converter keeps IDs, weights, record order and operation; it does not
remap vertices or sample edges. All seven historical cases converted. On AU
512 the current candidate host's CPU preflight accepted 390,847 old edges,
512 physical inserts and eight shards. The native AU 512 file has SHA-256
`092a84ab17b564cab854875e544f420635fe63cca5056e10c3842be912501e70`.
Conversion is offline input preparation, not a timed operation. A native
`--update-only` board run can validate
the actual G update and report its device events, but cannot on its own
replace the setup-inclusive panel. The frozen panel uses a different
host/layout implementation and modeled upload, while the current native
host's `--prepare-only` command also runs convergence oracles that do not
belong in an update-only setup timer. For a measured replacement, time
layout construction, batch preparation, initial/batch upload, and update
through completion on both arms under the same exclusions. Keep the
device-only evidence separately labeled.

## Figure 7: The Smallest Observed Margins

Holding the old Spine wall time fixed, the break-even reduction of the old
G+R wall is `1 - T_spine / T_gr`. This is a sensitivity calculation, not a
prediction of the repair's effect. All values below are from one measured
run per arm in the old matrix.

| Algorithm | Dataset | Old G+R ms | Old Spine ms | G+R wall reduction to tie |
| --- | --- | ---: | ---: | ---: |
| Weighted SSSP | AU | 18.418303 | 5.694790 | 69.08% |
| CC | AU | 11.919385 | 3.316460 | 72.18% |
| ResPR | R19 | 44.669267 | 32.375100 | 27.52% |

In particular, the R19 ResPR win could disappear with a 27.52% reduction in
the old G+R wall alone. Passing the 15% R retention gate cannot establish
that the **improvement relative to the old G+R** is smaller than 27.52%.
The two denominators differ. Do not sum the old per-CU adapter/gather/apply
times to estimate a removable fraction: those events overlap across CUs.

### Sensitivity To Removing All R Time

In the 24 old runs, the logged G update event time alone exceeds the matched
Spine wall time in two cases. For this counterfactual, freeze the measured
G update duration and the measured Spine wall time; set every other G+R
cost to zero, including R, host work and readback. This yields an optimistic
G+R latency floor, not a prediction of the new image's G timings.

| Algorithm | Dataset | Frozen G update ms | Frozen Spine wall ms | Floor / Spine |
| --- | --- | ---: | ---: | ---: |
| Weighted SSSP | PK | 15.825373 | 9.608190 | 1.65x |
| Weighted SSSP | R19 | 5.548182 | 4.271750 | 1.30x |

The other 22 runs remain undecided by this test, including every CC and
ResPR row. For example, R19 ResPR has 4.524463 ms of G update events versus
32.375100 ms of Spine wall time. None of these rows is admitted for the
repaired image by this calculation. Relinking changes placement, and keeping
the G XOs unchanged does not guarantee unchanged elapsed time on the board.

The integrated [ResPR host](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/24519a6/tools/sharded_k4_pagerank_native_host.cpp#L699)
uses round zero for correction and enqueues the adapter, gather and mux for
every destination shard before checking the active count. The old G+R hardware
logs record `pipeline_executions=1 propagation_rounds=0` in all eight cases;
the corresponding Spine logs record `iterations=0` with host correction
inside the resident timer. These are sparse update-and-correction results.
They neither establish an advantage for nonempty propagation nor imply that
R was idle. The separate [Flickr screen](RESIDENT_SCREEN.md) is for a batch
with nonempty thresholded propagation.

## Reproduce From The Old Raw Logs

Use the raw FPGA archive indexed by the frozen handoff, or the matching
original matrix on trifoliate:

```bash
matrix=/data/chuxiao/checks/grasu-replicated-host-singlepass-20261026-v1/matrix
rg '^RESIDUAL_PR_PMA_NATIVE_SHARDED_RESULT ' "$matrix"/respr-*/sample-1/gr/run.log
rg '^SPINE_RESIDENT_BENCHMARK_PASS ' "$matrix"/respr-*/sample-1/spine.stdout.txt
jq -s -r 'map({case:(.config.graph|split("/")[-1]),summary})
  | group_by(.summary.algorithm)[] | min_by(.summary.speedup_gr_over_spine)
  | [.summary.algorithm,.case,.summary.gr_wall_ms,.summary.spine_wall_ms,
     (100*(1-.summary.spine_wall_ms/.summary.gr_wall_ms))] | @tsv' \
  "$matrix"/{sssp,cc,respr}-*/results.json
```

To reproduce the G-only floor, join each single-pass `results.json` to its
`sample-1/gr/run.log`. Use `grasu_ms` from the weighted/CC timing line and
`update_ms` from the ResPR timing line, divided by
`summary.spine_wall_ms`. Keep only ratios above one. Do not include
`barrier_ms` or sum individual CU event times: they can overlap.

Revisit these decisions after the hardware controls complete. In particular,
do not merge a corrected R control with the old matrix and label the result
as newly measured end to end.
