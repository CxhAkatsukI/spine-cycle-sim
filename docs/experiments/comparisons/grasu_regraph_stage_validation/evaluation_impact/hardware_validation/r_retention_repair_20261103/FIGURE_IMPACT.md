# Figure Dependency Audit

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
