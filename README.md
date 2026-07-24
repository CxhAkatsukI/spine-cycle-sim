# spine-cycle-sim

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
[`docs/fine_grained_cycle_sim_contract_20260723.md`](docs/fine_grained_cycle_sim_contract_20260723.md).
The legacy Python/calibration path remains available for regression while that
new path is implemented.

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
[`docs/spine_full_tile_vertical_slice_20260723.md`](docs/spine_full_tile_vertical_slice_20260723.md)
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
[`docs/spine_dynamic_sssp_full_rebuild_20260725.md`](docs/spine_dynamic_sssp_full_rebuild_20260725.md).

## Current Scope

The legacy Python/calibration model targets trend validation against historical
exact split Spine hardware evidence. The fine-grained C++ path now executes
cold/hot maintenance and carry, all-level reading, tiny/full compute, finite
AXIS backpressure, AXI traffic, online SST-HBM, and multi-round weighted SSSP.
It intentionally does not model Vitis runtime overhead, PCIe transfers, RTL
routing effects, or total ASIC area/power. It is structural,
execution-driven evidence, not yet a hardware-cycle-calibrated replacement for
hw/hw_emu. The exact acceptance and remaining-gap matrix is in
[`docs/fine_grained_spine_phase2_acceptance_20260723.md`](docs/fine_grained_spine_phase2_acceptance_20260723.md).
The current payload-authoritative reader protocol is documented in
[`docs/spine_source_value_protocol_20260724.md`](docs/spine_source_value_protocol_20260724.md)
and
[`docs/spine_terminal_diagnostics_20260724.md`](docs/spine_terminal_diagnostics_20260724.md).
The persistent dirty-frontier coverage and ACK/clear lifecycle is documented
in
[`docs/spine_dirty_ownership_20260724.md`](docs/spine_dirty_ownership_20260724.md).
DEVICE-to-HOST limit handoff and payload-driven HOST tiled fallback are
documented in
[`docs/spine_host_tiled_fallback_20260724.md`](docs/spine_host_tiled_fallback_20260724.md).
The HLS-scoped `II=1` construction/replay pipelines, bounded ordered response
buffer, and AXIS backpressure evidence are documented in
[`docs/spine_hls_edge_pipeline_20260724.md`](docs/spine_hls_edge_pipeline_20260724.md).
The source-shaped per-interface AXI widths and explicit legacy compatibility
profile are documented in
[`docs/spine_axi_interface_profile_20260724.md`](docs/spine_axi_interface_profile_20260724.md).
The request-scoped maintenance read-beat stream, source scan ledger, and
report-derived count/L0-write loop timing are documented in
[`docs/spine_streamed_maintenance_scans_20260724.md`](docs/spine_streamed_maintenance_scans_20260724.md).
The source-ordered persistent dirty bitmap/list read-modify-write path,
duplicate suppression, and metadata lifecycle are documented in
[`docs/spine_dirty_rmw_pipeline_20260724.md`](docs/spine_dirty_rmw_pipeline_20260724.md).
The request-driven carry new-batch scan, lower-level head/lookahead buffering,
winner refill stalls, and remaining cursor/writer boundary are documented in
[`docs/spine_carry_refill_pipeline_20260724.md`](docs/spine_carry_refill_pipeline_20260724.md).
The persistent packed page-list count/ID ABI, lower-level retirement, and
metadata traffic evidence are documented in
[`docs/spine_page_list_metadata_20260724.md`](docs/spine_page_list_metadata_20260724.md).
The payload-driven carry cursor, HBM-authoritative source reconstruction,
per-page refill cycles, and malformed-index rejection are documented in
[`docs/spine_payload_driven_carry_cursor_20260724.md`](docs/spine_payload_driven_carry_cursor_20260724.md).
The online carry target writer, pending CSR packers, merge backpressure, and
component-local timing evidence are documented in
[`docs/spine_online_carry_writer_20260724.md`](docs/spine_online_carry_writer_20260724.md).
