# Spine Cycle Simulator Design

## Purpose

This simulator is an architecture exploration model for Spine. It is not a
replacement for HLS C simulation, Vitis hardware emulation, or FPGA validation.

The model answers questions such as:

- Which destination partition receives the pressure?
- When does L0 trigger a carry into L1?
- Does a workload fit the current partitioned L1 layout?
- How many simulated cycles are spent in FIFO backpressure, HBM activity, carry
  merge work, read maintenance, and SSSP propagation?

## Execution Model

The simulator uses an SST-style structure:

```text
Component.evaluate(cycle)
Component.commit(cycle)
FifoLink.commit()
Stats.sample/result dump
```

Components only see stable state during `evaluate`. FIFO pushes and pops become
visible after `commit`, which prevents same-cycle call-order artifacts.

## Modeled Spine v0 Components

```text
EdgeInput
PartitionRouter
Level0Buffer
Level1CarryMerge
HBMPartition[0..15]
ReadMaintenance
SSSPCompute
HostDrain
```

The first model is intentionally coarse. It preserves the design pressure points
that affect the current experiments, especially partition distribution and the
L0 to L1 carry boundary.

## HLS Relationship

The simulator does not parse or execute HLS C++. HLS and FPGA evidence provide:

- module boundaries
- FIFO and partition structure
- capacity constants
- target frequency
- behavior used to calibrate trends

The Python model re-expresses timing-relevant behavior at a higher level.

## Current Capacity Model

The default config follows the 2026-07-12 split Spine evidence:

```text
batch_size_edges = 131072
num_partitions = 16
level0_capacity_per_partition = 131072
level1_capacity_total = 262144
level1_capacity_per_partition = 16384
```

This means a one-partition `131072 + 1` insertion fails when the carry target is
L1, while a balanced `131072 + 1` insertion fits.
