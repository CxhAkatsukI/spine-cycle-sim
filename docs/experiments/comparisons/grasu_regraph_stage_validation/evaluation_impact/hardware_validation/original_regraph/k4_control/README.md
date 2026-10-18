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
edge `352 -> 43409`, rather than silently changing the graph. The separate
retained full study now admits Amazon as well: both Amazon and `skewed_sources`
pass all eight build/binding/repetition combinations. Its 24-row matrix contains
16 passes and eight unsupported duplicate-edge rows, with no errors or
memory-limit/OOM events. The
[retained result](../../../../../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/k4_control/README.md#retained-offline-result)
records the exact snapshot, hashes, limits and retained first harness failure.
It finished in 120.9 seconds with a 1.4-GiB peak. Neither the CPU runtime nor
the successful arithmetic checks are device latency measurements.

This is CPU semantic/preparation evidence only. No actual adapter/K4 board
timing or new paired Spine speedup is available. FullPR routing is still an
independent prerequisite; link success alone is not timing or board admission.
All final figures remain withheld until their corresponding gates pass.

The guarded K4 board-host implementation compiles in Release and UBSan.
Its retained complete preflight rechecks all 24 rows and full expected
graph/state buffers: 16 passes, eight explicit duplicate rejections, 142.1
seconds and a 1.422-GiB peak under a finite 4-GiB zero-swap cgroup. Its
preparation mode does not access a board. The implementation guide records
the exact snapshot, result hash and retained failed first harness attempt.

The separate board plan, qualified supervisor, exclusive worker and complete
18-row summary are implemented and CPU-tested, including failure retention
and independent raw-readback rechecking. They preserve six unsupported rows,
three repeats for each supported graph/binding and overlap-aware timing.
Actual bitstream/ABI qualification and repeated FPGA execution remain pending.
This is host readiness, not a new FPGA result.

The running FullPR route and complete host preflight have different integration
revisions. Shared graph/runtime-plan/l2 headers are identical; apply packing
changed. The board plan records both source identities and checks each FPGA
output independently, but explicitly withholds source-equivalence and
latest-revision-performance claims. An older routed result cannot silently
become a latest-version final figure.
