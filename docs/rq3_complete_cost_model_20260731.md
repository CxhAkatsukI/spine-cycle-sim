# RQ3 complete realized-work cost-model evidence

## Question and boundary

RQ3 asks whether Spine latency follows work realized by the update and graph
execution, rather than a fixed full-graph reset or a graph-size formula. The
analysis admits only Spine executions that pass both architecture-precision
and independent mathematical correctness oracles. Calibration rows alone fit
the E2E model; holdout rows never enter fitting.

The timed device boundary begins with a resident, sorted update buffer. Host
DMA and an external FLiMS sort are not timed. Residual PageRank's old/new-rank
correction and seed generation execute inside the simulated device boundary;
their serial device interval is attributed to `T_seed`. Every direct ledger
records these boundary choices explicitly.

## Direct ten-stage ledger

The simulator records six mutually exclusive maintenance stages:

- `T_xfer`: resident update transfer/control;
- `T_reduce`: duplicate reduction;
- `T_carry`: realized level carry and rewrite;
- `T_dir`: target and family-directory work;
- `T_seed`: dirty-source publication;
- `T_switch`: metadata and level-state publication.

Per-round reader and compute start/end timestamps then produce
`T_resolve`, `T_app`, `T_drain`, and `T_sync`. If reader and app overlap, the
interval is assigned to the component that gates completion. Thus the ten
stages are an exclusive critical path and must sum exactly to measured E2E
cycles. The current analysis has 47 direct ten-stage rows, and all 47 ledgers
close.

The five requested representative cases are:

| class | execution | E2E cycles |
| --- | --- | ---: |
| explicit zero-net | `rq3_zero_net_cc_u2` | 12,671 |
| shallow insertion | `956dc075c0655ff4a984` | 3,898,885 |
| deep carry | `rq3_trace_carry_l5_e8` | 31,249 |
| high-degree PageRank correction | `rq3_flickr_residual_correction_u8_eps1e6` | 370,417 |
| deletion fallback | `9a1d01bee8913cff1075` | 18,668,757 |

The zero-net representative requires the explicit `zero_net_no_repair` mode.
A trace with zero persisted records may still be classified for diagnostics,
but cannot replace this protocol-level representative.

## Realized-work relations

The analysis preserves all seven requested relations, including weak results:

| mechanism | samples | all-row R2 | result |
| --- | ---: | ---: | --- |
| `T_xfer+T_reduce` vs. `W_sort(B)` | 47 | 0.0116 | batch records alone omit fixed and contention effects |
| `T_carry` vs. `W_carry` | 5 | 0.9962 | realized carry records strongly explain carry time |
| `T_dir` vs. directory requests | 47 | 0.9981 | direct request count explains the covered directory path |
| `T_resolve+T_app` vs. `M_phys` | 47 | 0.4905 | physical records alone omit vertex apply and algorithm-state work |
| `T_seed` vs. `M_seed` | 44 | 0.9794 | seed work remains strongly predictive after device correction is included |
| `T_switch` vs. touched pages plus descriptors | 47 | 0.8753 | useful but incomplete across mixed classes |
| `T_drain` vs. source services plus reactivations | 40 | 0.3290 | one scalar does not explain topology and backpressure |

Weak single-variable relations are reported rather than hidden. They mean the
paper quantity is real and measured, but it is not by itself a transferable
latency predictor across all trace classes.

## E2E holdout model

The linear nonnegative model uses `W_sort`, `W_carry`, directory requests,
`M_phys`, `M_seed`, switch work, source/reactivation work, and algorithm apply
operations. Full PageRank is excluded because it is a full iteration rather
than a dynamic differential round. Variance-stabilized fitting prevents the
largest traces from completely dominating relative error.

Current evidence contains 95 correctness-admitted rows, 46 calibration rows,
and 39 real trace holdouts. On the real holdout:

- R2: 0.933;
- median absolute error: 26.46 percent;
- mean absolute error: 27.41 percent;
- maximum absolute error: 72.03 percent.

This supports bottleneck attribution and trend-level latency prediction. It
does not support a claim of cycle-for-cycle FPGA calibration or uniformly low
error on every topology.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

SPINE_RQ3_OUTPUT_DIR=/data/tmp/chuxiao/large_graph_campaign_v1/rq3_live \
  bash scripts/analyze_active_rq3.sh

/data/tmp/chuxiao/spine-paper-plot-venv/bin/python \
  scripts/render_rq3_realized_work.py \
  --analysis-dir /data/tmp/chuxiao/large_graph_campaign_v1/rq3_live \
  --figure-dir docs/figures \
  --data-dir docs/paper/data/rq3

python3 -m unittest -q tests.test_rq3_realized_work
```

The newest instrumentation plugin is
`/data/tmp/chuxiao/rq3-ten-stage-v3-20260731/libspine_cycle.so`, SHA-256
`87472a89dd6ac8446b6abe784d046fea685c5aae244b3986b00d4ea1cdb93f3b`.
