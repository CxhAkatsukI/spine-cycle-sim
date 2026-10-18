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

The supervisor accepts both hash-sealed local and remote algorithm returns.
Both must pass the same FullPR source/metadata/global-timing admission again
before any device worker. Accepting the local return format does not admit a
link by status alone, relax a timing requirement, or reuse an older bitstream.
The newest source closure needs a fresh arithmetic audit and board-host
preflight; the retained older runs below do not qualify it.

The running FullPR route and complete host preflight have different integration
revisions. Shared graph/runtime-plan/l2 headers are identical; apply packing
changed. The board plan records both source identities and checks each FPGA
output independently, but explicitly withholds source-equivalence and
latest-revision-performance claims. An older routed result cannot silently
become a latest-version final figure.

The retained prepare-only board plan is
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/original-r-k4-board-plan-v1`.
It rechecks all 24 preflight rows and declares 18 board rows: 12 executable
repetitions and six unsupported duplicate-edge rows, with no errors. Its
`results.json` SHA-256 is
`83ab5b3bad12134288ac7949d2c3c822b7dac0ed6e54361823de70ebd0e4f036`.
The finite 8/7-GiB zero-swap service finished in 22.3 seconds with a 109.1-MiB
peak; this preparation did not open an FPGA.

The qualified execution supervisor is
`spine-original-r-k4-board-supervisor-20261018-v1.service`, invocation
`d77374229f774efc926a18c9cecf679b`, using frozen runner `aecf4d6`. It waits for
the exact FullPR return-v2 invocation
`9f93433f962740e085a10b711c3394b4`. Its output is
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/original-r-k4-board-supervisor-v1`.
At the 17:08 UTC checkpoint it remains `WAITING_FOR_EXACT_ADMITTED_FULLPR_RETURN`.
It has finite 8/7-GiB limits, no swap, CPU affinity 124--125, a 146000-second
lifetime and an exclusive BDF lease before any guarded board worker. This
supervisor targets the independently frozen older FullPR source, not the
newer packing implementation queued for compilation. Neither a waiting
supervisor nor its prepare-only plan constitutes an adapter/K4 speed result.
