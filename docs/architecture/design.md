# Spine Cycle Simulator Design

## Purpose

This simulator is an architecture exploration model for the current Spine
branch at `origin/reduce-levels-for-routing` (`cbd3ceb`). It is not a
replacement for HLS C simulation, Vitis hardware emulation, or FPGA validation.

The model answers questions such as:

- Which destination partition receives the pressure?
- When does the 11-level ratio-2 binary carry advance from L0 into higher levels?
- Does a workload fit the current per-family level layout?
- Does measured destination in-degree trigger the hot/cold classifier?
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

The model is intentionally coarse. It preserves the design pressure points that
affect the current experiments, especially destination-range partitioning,
ratio-2 binary carry, hot/cold family placement, HBM bank service, and
tiny-active versus full convergence behavior.

## HLS Relationship

The simulator does not parse or execute HLS C++. HLS and FPGA evidence provide:

- module boundaries
- FIFO and partition structure
- capacity constants
- target frequency
- behavior used to calibrate trends

The Python model re-expresses timing-relevant behavior at a higher level.

## Current Capacity Model

The default config follows the newest Spine source inspected from
`origin/reduce-levels-for-routing`:

```text
MAX_N = 16777216
VS_PARTITION_SIZE = 1048576
batch_size_edges = 131072
num_partitions = 16
hot_shards = 16
num_levels = 11
level_size_ratio = 2
L1 capacity per family = ceil(262144 / 16) = 16384
L10 capacity per family = 8388608
family total capacity = 16891904
```

Families are:

```text
cold family 0..15: destination partition dst / VS_PARTITION_SIZE
hot family 16..31: hash(dst) % 16 for measured hot destinations
```

The hot/cold classifier mirrors the host reference at model scale: count
destination in-degree, leave the hot set empty for balanced graphs, and promote
high-degree destinations only when a cold destination family exceeds the
16,891,904-edge family cap.

This still means an incremental one-family `131072 + 1` update fails at the L1
binary carry boundary, while a balanced `131072 + 1` update fits. Separately, a
full raw RMAT preload can fit by classifying hot destinations and placing them
into the 16 hot shards; that is a graph-load/storage strategy, not the same as a
single concentrated incremental update.
