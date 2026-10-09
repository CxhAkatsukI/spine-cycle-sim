# Workloads and Comparisons

## Original-Publication Validation

Use the [GraSU / ReGraph study](grasu_regraph_publication_match/README.md)
for source differences, A/A4/B/C acceptance gates, fresh regression evidence,
and the explicit remaining work. It does not yet establish a published-speed match.

The [isolated G/A/A4/B stage study](grasu_regraph_stage_validation/README.md)
owns current G source/host controls, complete original-R finite models, and
the matched PMA/A4 state, traffic, and predicted-overhead study. The accepted
[SST/Spine refactor](../../repository/sst_spine_refactor/README.md) remains
unchanged. G finite timing, original-publication admission, physical timing,
and host/system composition remain unfinished; use its status table.

## For Current Figure Data

Use the [Figures 7--11 handoff](../../evaluation_refresh_20260810/figure7_10_handoff_v1/README.md).
The records below explain earlier workload construction and measurement choices;
they are not replacement inputs for that package.

## Workload and Measurement Background

- [AskUbuntu paper-scale workload](askubuntu_paper_scale_workload_20260728.md)
- [R19 source identity](r19_source_identity_20260729.md)
- [Shared comparison workloads](shared_comparison_workloads_20260725.md),
  [runner](shared_comparison_runner_20260725.md), and
  [analysis](shared_comparison_analysis_20260725.md)
- [SSSP warm-start measurement](spine_sssp_warm_start_measurement_20260730.md)

## Algorithm Experiments

- [Large-real three-algorithm comparison](large_real_three_algorithm_20260728.md)
- [Connected components publication study](connected_components_publication_20260728.md)
- [Residual PageRank warm start](deltahls_residual_warm_start_20260728.md)
- [Full PageRank large runtime](full_pagerank_large_runtime_20260726.md)

Before reusing a number, check old-state initialization, batch semantics,
convergence, timing inclusions, and capacity status in its owning contract.
Compacted topology, full physical IDs, update-only, and update-to-convergence
are different experimental scopes.
