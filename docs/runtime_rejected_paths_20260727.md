# Rejected simulator runtime paths

## Scope

These experiments tested host-runtime changes only. They did not change the
modeled accelerator, clock, FIFO/AXI/HBM behavior, or simulated cycle count.
The workload was Candidate10 Spine `syn_spread_e512` with thresholded residual
PageRank. It executes 4,778,979 core cycles and 410,621 DRAM requests.

All four `result.json` files are byte-identical, with SHA-256:

```text
da33883dd1f6c4f01ca1c1826e348e57bd7c02b07111e1e82169f92114e2c758
```

## Compiler optimization level

The production SST element Makefile uses `-O2 -g`. A temporary `-O3 -DNDEBUG`
build was compared on the same source and workload.

| SST element | Host wall seconds | Result |
| --- | ---: | --- |
| `-O2 -g` | 61.481 | baseline |
| `-O3 -DNDEBUG` | 61.657 | no benefit |

This was one interleaved run per build on a shared machine, so the sub-percent
difference is not a publishable regression. It is sufficient to reject the
claim that changing optimization level closes the large-graph runtime gap. The
Makefile change was reverted and never committed.

## SST thread scaling

SST 16.0.0 supports `--num-threads`. Four-thread runs were tested both with the
default partition and with the probe fixed to thread zero and memory
controllers assigned round-robin using `Component.setRank(0, thread)`.

| Configuration | Host wall seconds | Relative to single-thread `-O2` |
| --- | ---: | ---: |
| four threads, default partition | 175.745 | 2.86x slower |
| four threads, explicit controller partition | 174.916 | 2.85x slower |

The explicit run used all four host cores, but the probe-controller links have
1 ns latency. Conservative cross-thread synchronization at that granularity
costs more than parallel DRAMSim3 clocks save. Increasing link latency would
change modeled memory timing and was therefore not considered a valid runtime
optimization. All partitioning changes were reverted and never committed.

## DRAMSim3 build type

The live 50K-edge process maps:

```text
/data/feiyang/sst-build/DRAMsim3/libdramsim3.so
```

This is not an accidental debug backend. Its CMake cache records
`CMAKE_BUILD_TYPE=Release`, and
`build/CMakeFiles/dramsim3.dir/flags.make` records:

```text
CXX_FLAGS = -O3 -DNDEBUG -std=c++11 -fPIC -Wall
```

Rebuilding DRAMSim3 with ordinary release flags therefore cannot explain or
close the runtime gap. This audit changes no binary and no simulated event.

## Implication

The remaining large-run host cost is dominated by valid, already release-built
DRAMSim3 clock work on the 23 pseudo-channels bound by Candidate10, not by debug
compiler flags or idle FIFO polling. The accepted scheduler sleep changes
remain useful but small. A material speedup requires either a more efficient
exact DRAM backend integration or an event/wakeup scheme that preserves every
controller-visible ordering and refresh effect; coarse cycle skipping is not
authorized.

Raw outputs are retained outside Git:

```text
/data/tmp/chuxiao/scheduler_release_flags_o2_run1
/data/tmp/chuxiao/scheduler_release_flags_o3_run1
/data/tmp/chuxiao/sst_threads4_spread_residual_20260727
/data/tmp/chuxiao/sst_threads4_partitioned_spread_residual_20260727
```
