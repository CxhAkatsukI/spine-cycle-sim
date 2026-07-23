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

## Current Scope

The current model targets trend validation against the latest 134 MHz exact
split Spine hardware evidence on `reduce-levels-for-routing`. It intentionally
does not model Vitis runtime overhead, PCIe transfers, RTL routing effects, or
ASIC area/power. The B-stage maintenance model is structural and evidence
oriented: it estimates HLS scan/carry work and exposes diagnostics, but it is
not yet an AXI/stream/backpressure cycle-exact replacement for hw/hw_emu.
