# Bounded GraSU Cache And Revised FPGA Matrix

This study fixes input residency and repeated full-cache transfers, then
compares revised G+R with current Spine on actual FPGA hardware. It does not
modify the paper, assume Spine wins, or claim original-publication matching.

## Reading Order

The [Spine host follow-up](fpga_results_v2/README.md) is the current reviewed
delivery: all 24 cases pass, and Spine is faster on all eight graphs for
each algorithm. All eight ResPR cases have zero propagation rounds, so those
ratios measure update/correction/completion, not iterative propagation.
The older v1 package remains unchanged as historical evidence.

| Question | Read |
| --- | --- |
| What are the measured results, boundaries and limitations? | [Review summary](REPORT.md) |
| Where are the final 24-case data, figure, code and raw logs? | [Current FPGA package](fpga_results_v2/README.md), [preview](fpga_results_v2/figure/fpga_speedup.png), [review receipt](fpga_results_v2/review/README.md) |
| What changed from the older Spine hosts? | [Exact old/new medians](fpga_results_v2/comparison.csv), [retained v1 package](fpga_results_v1/README.md) |
| Where are the source, HLS, route and regression checks? | [Portable supporting evidence](implementation_evidence/README.md) |
| What exactly changed, and how were experiments executed? | [Technical runbook](RUNBOOK.md) |
| What does the isolated cache prediction demonstrate? | [Component ledger](component_prediction.csv), interpreted in the runbook |
| What is the accepted ReGraph publication-scale gap? | [Original-R board control](../../../grasu_regraph_publication_match/board_probe/dense_partitions.md) |

The v2 matrix contains 24 passing cases and 96 paired runs, including
warmups. Its portable archive, plot and diagnostics have passed independent
reparsing, isolated reproduction and visual review. SSSP speedups are
4.36--96.48x, CC 3.87--78.63x and zero-round ResPR 1.49--5.59x. These are
measured ratios on the frozen resident comparison, not an assumed win gate.

## Evidence Boundaries

- Source oracles and regression check correctness, state and traffic.
- HLS export checks the interface and synthesis result, not physical timing.
- Routed artifacts record actual clocks, including automatic scaling.
- FPGA pairs measure resident update-to-result wall time, including host
  relaunch and final readback; initial graph/PMA preparation is excluded.
- The simulator change is opt-in and default-off. These checks do not establish
  new full-system timing calibration or replace frozen simulator figures.

Raw machine-local evidence is under
`/data/chuxiao/checks/spine-cc-respr-host-20261026` for v2 and
`/data/chuxiao/builds/grasu-cache-extent-20261025` for v1 on trifoliate. The portable
supporting archive preserves its indexed records without copying large
bitstreams, graphs or compiler build trees into Git.

The integration repository owns production HLS and native hosts in
`docs/sharded_k4_cache_extent/` and `validation/cache_extent/`. This simulator
repository owns the prediction component, analysis and review deliverables.
