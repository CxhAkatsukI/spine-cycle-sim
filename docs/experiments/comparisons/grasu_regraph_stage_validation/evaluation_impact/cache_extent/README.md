# Bounded GraSU Cache And Revised FPGA Matrix

This study fixes input residency and repeated full-cache transfers, then
compares revised G+R with current Spine on actual FPGA hardware. It does not
modify the paper, assume Spine wins, or claim original-publication matching.

## Reading Order

The [Spine host follow-up](fpga_results_v2/README.md) is in progress. Its AU
gate passes; do not treat that gate as the complete matrix. The v1 package
below remains the last independently reviewed complete delivery until v2's
terminal verification and review finish.

| Question | Read |
| --- | --- |
| What are the measured results, boundaries and limitations? | [Review summary](REPORT.md) |
| Where are the final 24-case data, figure, code and raw logs? | [FPGA delivery package](fpga_results_v1/README.md), [preview](fpga_results_v1/figure/fpga_speedup.png), [review receipt](fpga_results_v1/review/README.md) |
| Where are the source, HLS, route and regression checks? | [Portable supporting evidence](implementation_evidence/README.md) |
| What exactly changed, and how were experiments executed? | [Technical runbook](RUNBOOK.md) |
| What does the isolated cache prediction demonstrate? | [Component ledger](component_prediction.csv), interpreted in the runbook |
| What is the accepted ReGraph publication-scale gap? | [Original-R board control](../../../grasu_regraph_publication_match/board_probe/dense_partitions.md) |

The v1 matrix contains 24 passing cases and 96 paired runs, including
warmups. Its portable archive, plot and diagnostics have passed independent
reparsing and isolated reproduction. The review summary reports both wins
and losses; correctness admission does not mean Spine wins every case.

## Evidence Boundaries

- Source oracles and regression check correctness, state and traffic.
- HLS export checks the interface and synthesis result, not physical timing.
- Routed artifacts record actual clocks, including automatic scaling.
- FPGA pairs measure resident update-to-result wall time, including host
  relaunch and final readback; initial graph/PMA preparation is excluded.
- The simulator change is opt-in and default-off. These checks do not establish
  new full-system timing calibration or replace frozen simulator figures.

Raw machine-local evidence is under
`/data/chuxiao/builds/grasu-cache-extent-20261025` on trifoliate. The portable
supporting archive preserves its indexed records without copying large
bitstreams, graphs or compiler build trees into Git.

The integration repository owns production HLS and native hosts in
`docs/sharded_k4_cache_extent/` and `validation/cache_extent/`. This simulator
repository owns the prediction component, analysis and review deliverables.
