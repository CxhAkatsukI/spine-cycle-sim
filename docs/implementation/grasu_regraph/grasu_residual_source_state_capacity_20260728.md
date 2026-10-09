# GraSU+ReGraph Residual Source-State Capacity Correction

## Trigger

The first 540,000-edge AskUbuntu residual-PageRank run activated three
65,536-vertex destination partitions.  The simulator rejected the frozen K=1
profile before cycle zero with:

```text
invalid GraSU-ReGraph configuration - source-state double-buffer stride is too small
```

This fail-closed result exposed a profile-capacity error.  It did not produce a
performance row.

## Root cause

Full PageRank stores one 32-bit value per source vertex, whereas thresholded
residual PageRank stores packed float32 rank and residual state, or 8 bytes per
vertex.  The residual profile inherited Full PageRank's 1 MiB ping-pong stride.
The frozen four-partition capacity requires:

```text
4 partitions * 65,536 vertices/partition * 8 bytes/vertex = 2 MiB
```

The physical source-state base remains 384 MiB in HBM pseudo-channels 1 and 3.
Increasing the buffer stride to 2 MiB does not overlap any other frozen region
inside the 512 MiB pseudo-channel.

## Correction

- K=1/K=2/K=4 residual profiles use a 2 MiB source-state stride.
- The freeze generator applies the algorithm-specific capacity.
- Address-map validation derives state width from the profile, checks the
  actual partition count before launching SST, and records the complete second
  ping-pong window.
- Capability, feasibility, and shared-experiment hashes are regenerated.

Weighted SSSP and Full PageRank profiles remain byte-identical.  The correction
changes capacity and physical ping-pong addresses only; it does not add a
pipeline, change latency parameters, or alter the selected K=1 comparator.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/freeze_grasu_regraph_k_pipeline.py
python3 -m unittest \
  tests.test_grasu_k_pipeline_freeze \
  tests.test_temporal_three_algorithm_analysis -v
```

The regression test also forces the old 1 MiB residual stride on the
three-partition dimensions and requires rejection before simulation.
