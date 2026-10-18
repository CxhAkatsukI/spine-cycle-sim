# Actual Adapter/K4 Control

The [implementation guide](../../../../../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/k4_control/README.md)
owns preparation, the fixed 24-row offline matrix and bounded reproduction.
The [C++ contract](../../../../../../../../cpp/tests/original_regraph/integrated/README.md)
defines the production graph buffers and guarded expected state. Original
11+3, original A4, actual adapter/K4 and complete G+R remain separate controls.

## Evidence Boundary

The original A4 and 11+3 FPGA controls already exist. The new path must consume
their exact frozen CSR, tasks, initial values and divisor binding, then build
the unmodified production destination-sharded PMA and 23-channel runtime
plan. No G update, source preparation, convergence, default-profile equivalence
or fixed/float bitwise equality is claimed. It is one matched static FullPR
superstep, damping 108/128, zero base/dangling share and initially zero rank.
It cannot prove a publication-performance match or isolation of adapter cost.

The new model independently validates CSR/task edge identity, graph mapping,
PMA edge conservation, packed gather, guarded graph/state capacity and bank
limits. A separate Python analysis rechecks the CSR arithmetic and exact
external gather/payload hashes, complete permutations and repeats/builds.
No simulator timing factor or HLS source is changed.

## Current Checkpoint

Five focused tests, including Release/UBSan builds, completed in a finite
2-GiB zero-swap cgroup in 22.1 seconds with a 384.6-MiB peak. They cover tiny
corruption fixtures and exact `skewed_sources`/`boundary_ring` controls; their
temporary model outputs were removed. `skewed_sources` passes both explicit
bindings. `boundary_ring` rejects 64 duplicate CSR records, first repeated
edge `352 -> 43409`, rather than silently changing the graph. Amazon and the
full 24-row study have no result at this checkpoint.

This is CPU semantic/preparation evidence only. No actual adapter/K4 board
timing or new paired Spine speedup is available. FullPR routing is still an
independent prerequisite; link success alone is not timing or board admission.
All final figures remain withheld until their corresponding gates pass.
