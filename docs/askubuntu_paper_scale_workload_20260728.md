# AskUbuntu near-paper-scale workload

## Purpose

The compact 8192-edge workloads do not activate multiple destination
partitions. This corpus provides a reproducible larger real-topology input for
multi-partition and dense-batch evaluation.

The GraSU paper reports 590000 initial AskUbuntu edge events. After removing
self edges and repeated directed edges, the supplied source contains only
544621 unique edges. The tracked corpus therefore uses a 540000-edge simple
graph and reserves 4096 subsequent unique edges for insertions. This is 91.5%
of the reported initial event count without changing simple-graph semantics.

The resulting graph has 157107 compact vertices. Under the frozen K=1
GraSU+ReGraph profile, it activates three 65536-vertex destination partitions.
It remains one partition under Spine's 1048576-vertex partition size; that
difference is part of the compared architectures rather than normalized away.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/prepare_candidate10_askubuntu_paper_scale.py
python3 scripts/prepare_candidate10_askubuntu_paper_scale.py --verify-only
```

The source archive is pinned by SHA-256 in
`spine_cycle_sim/experiments/temporal_real_batches.py`. The generated manifest
pins the graph, mapping, and each update stream independently. The formal
matrix uses insertion batches 8, 64, and 4096 to cover small and dense update
behavior.

