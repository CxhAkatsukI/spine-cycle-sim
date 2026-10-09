# Archived Workspace Overview

Preserved from the root README during the 2026-10-09 organization pass.
This is a historical development log, not the current getting-started guide.
Some commands refer to worktree locations that have since moved. Use the
[current root README](../../README.md) and [documentation index](../README.md)
for navigation. Original implementation and calibration claims below retain
their original scope; this archive does not promote them to current evidence.

Cycle-level simulator for the Spine dynamic graph accelerator.

This repository contains a first-version, SST-style Python simulator for
architecture exploration. It models the main timing and pressure points of the
current Spine design on `origin/reduce-levels-for-routing`:

- component/link execution with `evaluate` and `commit` phases
- finite FIFO backpressure
- 11-level partitioned ratio-2 binary carry
- 16 cold destination families plus 16 hot destination shards
- graph-agnostic hot/cold classification from measured destination in-degree
- current `dst / VS_PARTITION_SIZE` destination partitioning
- HLS-style B-stage maintenance timing for `sorted_edges` scan passes,
  L0 store, binary carry, sparse page-cursor reads, and hot/cold group scans
- tiny-active versus full-path convergence counters
- HBM request latency and bandwidth
- read-maintenance and SSSP propagation cost

The simulator is not a line-by-line translation of the HLS kernels. The HLS and
FPGA runs remain the functionality and calibration reference; this simulator is
the architecture exploration model.

Fine-grained C++ cycle simulation is being developed on
`codex/fine-grained-cycle-sim`. Its frozen execution, validation, comparison,
and evidence contract is documented in
[`docs/fine_grained_cycle_sim_contract_20260723.md`](../architecture/fine_grained_cycle_sim_contract_20260723.md).
The legacy Python/calibration path remains available for regression while that
new path is implemented.

The frozen native, HLS-emulated, normalized, and projected GraSU + ReGraph comparison
contract is documented in
[`docs/grasu_regraph_pma_native_contract_20260725.md`](../architecture/grasu_regraph_pma_native_contract_20260725.md).
It records the real GraSU PMA topology and prevents the existing capacity-wide
conversion cost from being silently removed from native results.

A conversion-free weighted-PMA HLS implementation now passes whole-system
`sw_emu` against an independent weighted-SSSP oracle. Its 15-CU topology,
full-word delete/insert update semantics, requested clock, fixed four-round
host schedule, and non-performance claim boundary are frozen in
[`docs/grasu_regraph_weighted_pma_hls_sw_emu_20260726.md`](../experiments/calibration/grasu_regraph_weighted_pma_hls_sw_emu_20260726.md).
It remains fail-closed as `profile_only` until the simulator executes those
exact semantics.

The first executable GraSU comparator slice now performs payload-backed PMA
insert/delete updates through finite AXIS, AXI, and shared-HBM components. Its
scope, byte ledger, and correctness evidence are in
[`docs/grasu_native_update_vertical_20260725.md`](../implementation/grasu_regraph/grasu_native_update_vertical_20260725.md).

The existing-HLS native baseline now executes the full serial GraSU update,
PMA compactor, edge-array ReGraph SSSP path on SST-HBM with no hidden
conversion. It also reproduces the host's update-density vertex reorder and
records external/internal source IDs. Two FPGA workloads have exact
graph/source/PMA/slot/superstep and SSSP alignment; absolute timing remains an
explicitly trend-only result. See
[`docs/grasu_regraph_native_e2e_20260725.md`](../implementation/grasu_regraph/grasu_regraph_native_e2e_20260725.md).
The fail-closed algorithm capability catalog now makes the remaining native
boundary machine-readable: the existing HLS profile can execute only
unit-weight fixed-superstep SSSP, while weighted SSSP and both PageRank modes
remain normalized simulation implementations. See
[`docs/grasu_regraph_algorithm_capabilities_20260726.md`](../implementation/grasu_regraph/grasu_regraph_algorithm_capabilities_20260726.md).
The same three Map/Reduce/Apply policies now have an eight-lane HLS arithmetic
core and pass Vitis `sw_emu` compilation. This is incremental policy evidence,
not a native PageRank whole-system claim; the exact evidence boundary and
remaining integration modules are recorded in
[`docs/hls_algorithm_policy_evidence_20260726.md`](../experiments/calibration/hls_algorithm_policy_evidence_20260726.md).
The frozen ten-case U55C calibration/holdout matrix now matches every graph,
reordered source, PMA/compact count, superstep count, and SSSP output. Its
unfitted timing remains optimistic by about 50% E2E median and is explicitly
trend-only; raw evidence, runtime, and component diagnostics are in
[`docs/grasu_native_hw_matrix_20260725.md`](../experiments/calibration/grasu_native_hw_matrix_20260725.md).
An explicit measured-envelope layer now preserves those execution-driven core
cycles while accounting separately for update, compactor, ReGraph controller,
and host/event-window gaps. Five calibration cases predict the frozen holdout
at 0.40% median and 2.38% maximum E2E error; four tiny cases use six FPGA
repeats, while the remaining single-sample component limitations stay visible.
See
[`docs/grasu_native_timing_envelope_20260725.md`](../implementation/grasu_regraph/grasu_native_timing_envelope_20260725.md).
Completed native update and conversion components are now removed from the
host scheduler only after their AXI ports and shared backend drain. This leaves
the cycle/counter result byte-identical while reducing native SST wall time by
about 10% on the 64-superstep chain; see
[`docs/grasu_native_scheduler_runtime_20260725.md`](../implementation/grasu_regraph/grasu_native_scheduler_runtime_20260725.md).
Binding DRAMSim3 only to the five HBM pseudo-channels reachable by the native
HLS topology preserves the physical 32-channel namespace and gives an exact
full-versus-sparse result check. With that host optimization, the complete
4096-superstep stress case now passes in 19.16 minutes. Its structural,
correctness, pressure, DRAM, and explicit unfitted-timing evidence is in
[`docs/grasu_native_stress_runtime_20260725.md`](../implementation/grasu_regraph/grasu_native_stress_runtime_20260725.md).

The PMA-native ReGraph SSSP path now includes finite gather/merger, merger/apply,
and apply/HBM-wrapper streams with online SST-HBM backpressure. Its overlap and
pressure evidence are in
[`docs/grasu_regraph_stream_overlap_20260725.md`](../implementation/grasu_regraph/grasu_regraph_stream_overlap_20260725.md).
The follow-up closes the HLS gather RAW-forwarding and fixed-window source-cache
controller gaps; the exact source mapping, cross-window test, and updated SST
ledger are in
[`docs/grasu_regraph_gather_source_cache_20260725.md`](../implementation/grasu_regraph/grasu_regraph_gather_source_cache_20260725.md).
The weighted dynamic extension carries the ReGraph `dst19 + weight12` edge word
through GraSU PMA updates and validates PMA state plus SSSP against independent
oracles. Its single-partition boundary and required HLS delta are documented in
[`docs/grasu_regraph_weighted_dynamic_sssp_20260725.md`](../implementation/grasu_regraph/grasu_regraph_weighted_dynamic_sssp_20260725.md).

The same PMA-native path now runs fixed-iteration Full PageRank with explicit
HBM degree reads, dangling redistribution, complete partition sweeps, and both
float32 architecture and float64 mathematical oracles. Its timing ledger and
untimed dynamic-degree boundary are documented in
[`docs/grasu_regraph_full_pagerank_20260725.md`](../implementation/grasu_regraph/grasu_regraph_full_pagerank_20260725.md).

Thresholded residual PageRank uses the same PMA-native path with signed
residual push and an explicit packed 64-bit `{rank, residual}` vertex state.
This doubles source-cache and apply traffic relative to Full PageRank rather
than hiding the additional state in the host model. Its dual-oracle evidence
and exact claim boundary are documented in
[`docs/grasu_regraph_residual_pagerank_20260725.md`](../implementation/grasu_regraph/grasu_regraph_residual_pagerank_20260725.md).

The compute path now supports multiple destination partitions while preserving
ReGraph's 19-bit local-destination ABI. All partitions share one old source
epoch and cross a barrier before state swap or convergence; Full and residual
PageRank count dangling mass once per superstep. The serial one-pipeline
execution contract, HLS mapping, and three-algorithm evidence are documented in
[`docs/grasu_regraph_multi_partition_20260725.md`](../implementation/grasu_regraph/grasu_regraph_multi_partition_20260725.md).

Partitioned GraSU updates now maintain the PageRank out-degree array through
timed 4-byte HBM read-modify-writes and feed the same PMA and degree payloads
directly into serial multi-partition ReGraph. The normalized SST run closes the
cycle, byte, backend-request, DRAM-command, PMA, degree, and dual-oracle ledgers
without an intermediate conversion layer. Its explicit native-versus-proposed
claim boundary is documented in
[`docs/grasu_regraph_partitioned_dynamic_pagerank_20260725.md`](../implementation/grasu_regraph/grasu_regraph_partitioned_dynamic_pagerank_20260725.md).

Post-implementation FPGA area and timing evidence is now hash-pinned and
machine parsed from archived Vivado reports and xclbin metadata. It separates
requested timing closure from packaged auto-scaled clocks, uses the formally
accepted Spine route as the primary result, and retains the canonical 134 MHz
route as negative evidence. These numbers are native and non-normalized; see
[`docs/fpga_routed_area_timing_20260725.md`](../experiments/cost_models/fpga_routed_area_timing_20260725.md).

Execution-driven physical array activity now feeds hash-pinned CACTI-P 6.5
scratchpad characterizations while DRAMSim3 HBM energy remains a separate
ledger. The first Spine and normalized GraSU/ReGraph vertical runs close every
HBM request and explicitly label selected-array plus HBM energy as partial,
not FPGA or total accelerator energy. See
[`docs/onchip_energy_evidence_20260725.md`](../experiments/cost_models/onchip_energy_evidence_20260725.md).

A system-neutral comparison corpus now freezes 20 disjoint synthetic fixtures,
three compact real-dataset slices, identical algorithm parameters, and 73 run
cases. It is input evidence only; no performance result is inferred until both
architectures pass the shared runner and dual-oracle gates. See
[`docs/shared_comparison_workloads_20260725.md`](../experiments/comparisons/shared_comparison_workloads_20260725.md).

The shared runner dispatches byte-identical inputs to normalized Spine and
conversion-free GraSU/PMA-native-ReGraph, enforces independent architecture and
mathematical oracles, closes each explicitly bound DRAM request ledger within
the shared 32-channel physical namespace, and emits paired cycle/runtime rows.
The complete frozen matrix now passes all 146 system rows and 73 pairs. Spine
wins 48 pairs with a 1.849x geometric-mean normalized cycle speedup, while the
three compact real-dataset validation slices remain effectively tied overall
(0.912x geometric mean) and are not full-dataset performance evidence. See
[`docs/shared_comparison_runner_20260725.md`](../experiments/comparisons/shared_comparison_runner_20260725.md).
The fail-closed results and frozen raw evidence are documented in
[`docs/shared_comparison_analysis_20260725.md`](../experiments/comparisons/shared_comparison_analysis_20260725.md).

The normalized SST runners retain a 32-channel physical namespace while
instantiating only profile/workload-reachable DRAMSim3 controllers by default.
Six full-vs-sparse cases prove byte-identical cycles, results, and active DRAM
transcripts across all three algorithms and both architectures. Sparse DRAM
energy excludes unbound-channel idle/background energy. See
[`docs/normalized_sparse_hbm_binding_20260725.md`](../architecture/normalized_sparse_hbm_binding_20260725.md).

## Quick Start

Run one workload:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_spine_sim.py \
  --workload chain \
  --vertices 1024 \
  --edges 1023 \
  --source 0 \
  --config configs/spine_current.yaml \
  --out-dir results/demo_chain
```

Run the validation-oriented workload suite:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_spine_suite.py \
  --config configs/spine_current.yaml \
  --out-dir results/spine_v0_suite
```

Run maintenance-focused microbenchmarks:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_maintenance_microbench.py \
  --out-dir results/maintenance_phase1_microbench
```

Run tests:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 -m unittest discover -s tests

cmake -S . -B build/cycle-core -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/cycle-core
ctest --test-dir build/cycle-core --output-on-failure
```

Build and run the online SST-HBM integration smoke:

```bash
cd /home/chuxiao/spine-cycle-sim
make -C cpp/sst
SPINE_SST_REQUESTS=256 \
SPINE_SST_OUTPUT=build/sst/online_memory_probe.json \
/data/feiyang/sst/bin/sst \
  --add-lib-path=/home/chuxiao/spine-cycle-sim/build/sst \
  sst/online_memory_probe.py
```

Run the automated sequential/cross-row/mixed acceptance suite:

```bash
python3 scripts/run_sst_memory_smoke.py \
  --out-dir results/sst_memory_smoke
```

Run the real-edge Spine L0/reader/tiny-SSSP slice on 32-channel SST-HBM:

```bash
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 \
  --out-dir results/sst_spine_vertical_levels_20260723
```

Run the independent cold-L1 carry plus hot-L0 scenario:

```bash
python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot \
  --out-dir results/sst_spine_carry_hot_20260723
```

Run the real Amazon full-tile compute microbenchmark on SST-HBM:

```bash
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_full_compute \
  --out-dir results/sst_spine_full_compute_20260723
```

This compute-only mode keeps the finite AXIS, compute state machine, AXI
masters, and DRAMSim3 HBM while bypassing maintenance and reader. See
[`docs/spine_full_tile_vertical_slice_20260723.md`](../implementation/spine/spine_full_tile_vertical_slice_20260723.md)
for the exact claim boundary and accepted evidence.

Run the file-backed weighted SSSP workload to frontier convergence:

```bash
python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp \
  --out-dir results/sst_spine_weighted_sssp_20260723
```

This mode performs maintenance once, then reuses persistent levels, vertex
state, AXIS links, AXI masters, and SST-HBM across all frontier rounds.

Run positive incremental repair, deletion fallback, and weight-increase
fallback in one persistent SST process per scenario:

```bash
python3 scripts/run_sst_spine_vertical.py --scenario dynamic_sssp \
  --out-dir results/sst_spine_dynamic_sssp
python3 scripts/run_sst_spine_vertical.py --scenario dynamic_sssp_delete \
  --out-dir results/sst_spine_dynamic_delete
python3 scripts/run_sst_spine_vertical.py --scenario dynamic_sssp_increase \
  --out-dir results/sst_spine_dynamic_increase
```

Positive updates preserve distances and levels. Signed deletions explicitly
time metadata invalidation, graph rebuild, vertex-state reset, and full SSSP
recomputation. See
[`docs/spine_dynamic_sssp_full_rebuild_20260725.md`](../implementation/spine/spine_dynamic_sssp_full_rebuild_20260725.md).

Run and analyze the frozen normalized cross-architecture matrix:

```bash
python3 scripts/run_shared_comparison_matrix.py \
  --out-dir results/shared_comparison_sparse_full_20260725 \
  --jobs 4 --timeout-seconds 1800 --resume --no-build
python3 scripts/analyze_shared_comparison_matrix.py \
  --matrix-dir results/shared_comparison_sparse_full_20260725 \
  --out-dir results/shared_comparison_sparse_analysis_20260725
```

The analyzer refuses partial matrices and labels DRAM energy as sparse
active-channel evidence. See
[`docs/shared_comparison_analysis_20260725.md`](../experiments/comparisons/shared_comparison_analysis_20260725.md).

Run the paired Full PageRank dense-batch timing and explicit capacity-cliff
checks with the commands in
[`docs/dense_full_pagerank_20260726.md`](../implementation/algorithms/dense_full_pagerank_20260726.md).

The 50,000/100,000-edge Amazon real-slice runtime stress gates are documented in
[`docs/full_pagerank_large_runtime_20260726.md`](../experiments/comparisons/full_pagerank_large_runtime_20260726.md).

## Current Scope

The legacy Python/calibration model targets trend validation against historical
exact split Spine hardware evidence. The fine-grained C++ path now executes
cold/hot maintenance and carry, all-level reading, tiny/full compute, finite
AXIS backpressure, AXI traffic, online SST-HBM, and multi-round weighted SSSP.
It intentionally does not model Vitis runtime overhead, PCIe transfers, RTL
routing effects, or total ASIC area/power. It is structural,
execution-driven evidence, not yet a hardware-cycle-calibrated replacement for
hw/hw_emu. The exact acceptance and remaining-gap matrix is in
[`docs/fine_grained_spine_phase2_acceptance_20260723.md`](early_models/fine_grained_spine_phase2_acceptance_20260723.md).
The current payload-authoritative reader protocol is documented in
[`docs/spine_source_value_protocol_20260724.md`](../implementation/spine/spine_source_value_protocol_20260724.md)
and
[`docs/spine_terminal_diagnostics_20260724.md`](../implementation/spine/spine_terminal_diagnostics_20260724.md).
The persistent dirty-frontier coverage and ACK/clear lifecycle is documented
in
[`docs/spine_dirty_ownership_20260724.md`](../implementation/spine/spine_dirty_ownership_20260724.md).
DEVICE-to-HOST limit handoff and payload-driven HOST tiled fallback are
documented in
[`docs/spine_host_tiled_fallback_20260724.md`](../implementation/spine/spine_host_tiled_fallback_20260724.md).
The HLS-scoped `II=1` construction/replay pipelines, bounded ordered response
buffer, and AXIS backpressure evidence are documented in
[`docs/spine_hls_edge_pipeline_20260724.md`](../implementation/spine/spine_hls_edge_pipeline_20260724.md).
The source-shaped per-interface AXI widths and explicit legacy compatibility
profile are documented in
[`docs/spine_axi_interface_profile_20260724.md`](../architecture/spine_axi_interface_profile_20260724.md).
The request-scoped maintenance read-beat stream, source scan ledger, and
report-derived count/L0-write loop timing are documented in
[`docs/spine_streamed_maintenance_scans_20260724.md`](../implementation/spine/spine_streamed_maintenance_scans_20260724.md).
The source-ordered persistent dirty bitmap/list read-modify-write path,
duplicate suppression, and metadata lifecycle are documented in
[`docs/spine_dirty_rmw_pipeline_20260724.md`](../implementation/spine/spine_dirty_rmw_pipeline_20260724.md).
The request-driven carry new-batch scan, lower-level head/lookahead buffering,
winner refill stalls, and remaining cursor/writer boundary are documented in
[`docs/spine_carry_refill_pipeline_20260724.md`](../implementation/spine/spine_carry_refill_pipeline_20260724.md).
The persistent packed page-list count/ID ABI, lower-level retirement, and
metadata traffic evidence are documented in
[`docs/spine_page_list_metadata_20260724.md`](../implementation/spine/spine_page_list_metadata_20260724.md).
The payload-driven carry cursor, HBM-authoritative source reconstruction,
per-page refill cycles, and malformed-index rejection are documented in
[`docs/spine_payload_driven_carry_cursor_20260724.md`](../implementation/spine/spine_payload_driven_carry_cursor_20260724.md).
The online carry target writer, pending CSR packers, merge backpressure, and
component-local timing evidence are documented in
[`docs/spine_online_carry_writer_20260724.md`](../implementation/spine/spine_online_carry_writer_20260724.md).
