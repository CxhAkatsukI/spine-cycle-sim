# Script Guide

These are CLI entry points, not one chronological pipeline. Similar names with
different `vN`, candidate, or date suffixes may consume different contracts.
Choose an evidence package and profile first, then choose its documented runner.

## Execution and Validation

| Task | Entry | Caution |
| --- | --- | --- |
| Inspect repository structure | [audit_repository_structure.py](audit_repository_structure.py) | Read-only unless catalog generation is requested |
| Spine SST component/system runs | [run_sst_spine_vertical.py](run_sst_spine_vertical.py) | Multiple explicit modes; follow the selected profile's contract |
| G+R weighted SSSP | [run_sst_grasu_regraph_hls_weighted.py](run_sst_grasu_regraph_hls_weighted.py) | Ported HLS topology, not original-publication equivalence |
| Connected components | [run_sst_connected_components.py](run_sst_connected_components.py) | Architecture and initialization policy must match the experiment |
| G+R Residual PR | [run_sst_grasu_regraph_hls_residual_pagerank.py](run_sst_grasu_regraph_hls_residual_pagerank.py) | Correction and propagation are distinct work |
| Frozen Spine matrix | [run_current_fpga_spine_compacted_matrix.py](run_current_fpga_spine_compacted_matrix.py) | Inspect plugin identity, input roots, memory reserve, and defaults |
| Frozen G+R matrix | [run_current_fpga_grasu_frozen_matrix.py](run_current_fpga_grasu_frozen_matrix.py) | Same checks; a filename containing `current` is not proof of currency |
| Persistent update-only case | [run_current_fig8_update_only_case.py](run_current_fig8_update_only_case.py) | Update-only scope, not graph convergence |
| Profile/capability checks | [generate_grasu_regraph_sharded_k4_hls_profiles_v8.py](generate_grasu_regraph_sharded_k4_hls_profiles_v8.py) | Use its check mode for frozen-profile validation |
| Original-publication comparison gates | [audit_grasu_regraph_publication.py](audit_grasu_regraph_publication.py) | Source audit; not a completed published-throughput experiment |
| Full temporal publication input controls | [audit_publication_workloads.py](audit_publication_workloads.py) | Complete AU/SU/WK order/batch/unique counts and explicitly post-hoc denominator clue; not recovered author updates or a timing match |
| Upstream publication history | [audit_upstream_publication_history.py](audit_upstream_publication_history.py) | Complete fetched/pinned author history, deleted archive and AE/Release comparison; read-only source admission, not timing reproduction |
| Independent original-source stage controls | [run_upstream_stage_controls.py](run_upstream_stage_controls.py) | Original cache/Little/Big source-functional checks; no device-cycle or published-speed claim |
| Actual routed sharded-K4 stage diagnostic | [run_sharded_k4_stage_diagnostic.py](run_sharded_k4_stage_diagnostic.py) | Paired unchanged xclbin, original/trace-disabled/trace-enabled hosts; event overlap is not exclusive row-stall time or original-A4 performance |
| Sharded-K4 adapter scheduling ablations | [synthesize_sharded_k4_adapter_candidates.py](synthesize_sharded_k4_adapter_candidates.py) | Four explicit default-off candidate combinations; compile only, no routed hardware speedup |
| Sharded-K4 adapter RTL gate | [cosim_sharded_k4_adapter.py](cosim_sharded_k4_adapter.py) | Exact source-pinned packet comparison; HLS AXI simulation, not FPGA |
| Sharded-K4 single-XO replacement | [route_sharded_k4_adapter.py](route_sharded_k4_adapter.py) | ABI/connectivity admission, aggregate RSS/reserve watchdog; link success is not board admission |
| Routed candidate timing/topology gate | [admit_sharded_k4_bitstream.py](admit_sharded_k4_bitstream.py) | Checks setup/hold/pulse timing, clock and normalized XRT HBM connections before programming |
| Original/candidate K4 board comparison | [compare_sharded_k4_bitstreams.py](compare_sharded_k4_bitstreams.py) | Matched host/input/state/convergence with alternating repeats; not original-A4 or publication matching |
| Package actual-K4 diagnostic evidence | [package_sharded_k4_stage_diagnostic.py](package_sharded_k4_stage_diagnostic.py) | Immutable raw log/result index, conservative checkpoint, no paper/figure modification |
| Original G prepared-PMA kernel composition | [run_original_grasu_source_path.py](run_original_grasu_source_path.py) | Search/BIPA/dispatch/cache/DDR, complete state, repetitions and UBSan; not host preparation, finite timing or paper throughput |
| Original G host/kernel/merge control | [run_original_grasu_host.py](run_original_grasu_host.py) | Trace-aware preparation, two bounds guards, initialized padding and exact old G regression; functional, not device timing |
| Original G DDR shared-memory RTL control | [run_original_grasu_ddr_rtl.py](run_original_grasu_ddr_rtl.py) | Fresh unchanged DDR synthesis, aliased finite bus, complete state, repetitions and UBSan; isolated component evidence, not board/full-G/publication timing |
| Original G finite composition | [run_original_grasu_finite.py](run_original_grasu_finite.py) | Shared four-bank search/cache/DDR, independent state and request ledgers, repeated/registration-order controls; predicted timing, not publication matching |
| Existing PMA adapter source and shared A4 wiring | [run_original_regraph_adapter_source.py](run_original_regraph_adapter_source.py) | Full task/packet multiset checks and exact whole-A4 extraction regression; not finite adapter timing or overhead |
| Finite matched PMA/original A4 study | [run_pma_regraph_control.py](run_pma_regraph_control.py) | Same downstream and input-credit budget, full state/traffic, cold/stale source controls and explicit timing assumptions; not FPGA/publication matching |
| Original-source HLS schedules | [run_upstream_stage_synthesis.py](run_upstream_stage_synthesis.py) | Bounded isolated synthesis; source/tool/platform differences explicit; no FPGA timing claim |
| HLS schedule analysis | [analyze_upstream_stage_synthesis.py](analyze_upstream_stage_synthesis.py) | Checks contracts/report hashes and indexes all attempts; never invents workload cycles or rates |
| Independent original-R finite Gather/merge | [run_original_regraph_gather_validation.py](run_original_regraph_gather_validation.py) | Isolated build, complete source-word comparison, finite-buffer and negative controls; not whole-R throughput |
| Independent original-R memory/frontend | [run_original_regraph_frontend_validation.py](run_original_regraph_frontend_validation.py) | Request-dependent source controls, finite AXI/Scatter/Gather, old-result equality, repeated counters and undefined-behavior checks; stops before Apply |
| Independent original-R PR state | [run_original_regraph_state_validation.py](run_original_regraph_state_validation.py) | Original Apply/writer captures, finite degree/writeback, resident iterations and old frontend/Gather equality; predicted timing only |
| Original-host graph preparation | [run_original_regraph_inputs.py](run_original_regraph_inputs.py) | Original DBG/partition/schedule/PR initialization, full-edge oracle and repeated normal/UBSan captures; no device timing |
| Independent original-A4 full graph execution | [run_original_regraph_a4.py](run_original_regraph_a4.py) | Complete pre-Apply/state/finite-memory gates, exact legacy defaults, repeated/resource/rejection/UBSan checks; mock-memory timing prediction only |
| Independent original-R Big routing/Gather | [run_original_regraph_big_validation.py](run_original_regraph_big_validation.py) | Original omega/bank/global-merger values, finite pressure, reuse and exact whole-A4 regression; excludes Big source memory and publication timing |
| Independent original-R Big memory/Scatter | [run_original_regraph_big_frontend_validation.py](run_original_regraph_big_frontend_validation.py) | Complete original request/response/update capture, finite cache/AXI ledgers, pressure and old-result equality; excludes mixed-system and publication timing |
| Independent original-R mixed whole graph | [run_original_regraph_mixed.py](run_original_regraph_mixed.py) | Complete 11+3 graph state/traffic, explicit publication-tail allocation control, exact old A4/Big results and UBSan; not a publication-speed match |
| Native validation extraction handoff | [package_publication_validation_smoke.py](package_publication_validation_smoke.py) | Preserves exact result equality and the known 2-round rejection |
| C++ G+R extraction regression | [run_grasu_refactor_regression.py](run_grasu_refactor_regression.py) | Five fixed cases, explicit plugin binding, exact full-result comparison; not performance calibration |
| SST/Spine extraction regression | [run_component_refactor_regression.py](run_component_refactor_regression.py) | Frozen matrix; compare every result field, and keep known rejections separate from correctness admissions |

## Analysis and Figures

| Task | Entry | Scope |
| --- | --- | --- |
| Hardware-component timing analysis | [analyze_current_fpga_components.py](analyze_current_fpga_components.py) | Check calibration and holdout status; not a blanket calibration certificate |
| Figure 8 export | [export_persistent_update_setup_fig8.py](export_persistent_update_setup_fig8.py) | Setup-inclusive update-only evidence |
| Figure 9 export | [export_current_fpga_fig9.py](export_current_fpga_fig9.py) | Accepted-byte and HBM-energy ledgers |
| RQ3 realized-work analysis | [analyze_rq3_realized_work.py](analyze_rq3_realized_work.py) | Model fitting and prediction, not FPGA stage counters |
| Complete Figures 7--11 rendering | [handoff render_all.py](../docs/evaluation_refresh_20260810/figure7_10_handoff_v1/render_all.py) | Use the complete handoff, not a similarly named earlier renderer |

The [complete catalog](CATALOG.md) includes the retained investigation and
historical commands. Categorization describes command role, not acceptance
status. Do not delete a command merely because a later version exists.

## Before Launching a Campaign

1. Read the owning contract and `--help`; inspect default output/workload paths.
2. Record source revision, profiles, compiler/build flags, plugin SHA-256, and
   any uncommitted changes relevant to execution.
3. Use a new output directory. Do not overwrite accepted or failed evidence.
4. Set parallelism using measured peak memory and a reserve, not CPU count.
5. Keep simulator wall time separate from modeled device latency and measured
   hardware event windows.

The navigation cleanup did not change numerical behavior. The subsequent
[native validation extraction](../docs/experiments/comparisons/grasu_regraph_publication_match/README.md)
preserves CLI/import compatibility and exact smoke outputs; models, profiles,
calibration coefficients, and figure inputs remain unchanged.
