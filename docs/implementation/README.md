# Implementation Guide

Read the [architecture contracts](../architecture/README.md) first, then the
component relevant to the change.

| Component | Guide | Questions it answers |
| --- | --- | --- |
| Spine | [Spine implementation](spine/README.md) | Maintenance, carry, owner scheduling, reading, and propagation |
| GraSU + ReGraph | [G+R implementation](grasu_regraph/README.md) | PMA updates, adapter, sharding, reader/compute paths, and partition limits |
| Runtime and memory | [Runtime integration](runtime/README.md) | SST, AXI scheduling, DRAMSim3, and simulator execution |
| Algorithm policies | [Algorithm implementation](algorithms/README.md) | Arithmetic, timing primitives, and fallback protocols |

For the actual source boundaries, use the [C++ code map](../../cpp/README.md).
For executable workflows, use the [script guide](../../scripts/README.md).
The dated documents here are implementation records, not a list of currently
accepted benchmark results. Those belong to the [experiment guide](../experiments/README.md)
and the selected evidence package.
