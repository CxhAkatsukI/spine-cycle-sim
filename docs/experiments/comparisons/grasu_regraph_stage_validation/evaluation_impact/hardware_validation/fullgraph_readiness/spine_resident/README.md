# Fixed-Spine Resident Board Protocol

## Scope And Boundary

This is the Spine half of the new eight-graph hardware comparison, not a
simulator calibration or a completed speedup result. It reuses the existing
150-MHz owner-FIFO bitstreams and adds an opt-in host benchmark. Kernel source,
connectivity, bitstreams and algorithm arithmetic are unchanged.

Both hosts use the boundary
`resident_update_to_final_readback_wall_including_host_relaunch`: start with
the old-converged state and the update batch resident; start one continuous
wall timer immediately before update launch; stop after the converged result
has been read back. Graph construction, programming, initial preload and
independent final CPU validation are outside. Actual work between these events
is inside, including inter-round host work and transfers. This is not complete
CPU setup latency and must not be labeled as such.

The fixed Spine driver reads full state each round; that overhead is counted.
Its residual-PR degree/correction/seed remains host work, also counted. These
are explicit implementation differences, not an all-device claim. Historical
`dynamic_setup_inclusive_ms` sums local windows and is not used for this ratio.

## Ownership And Acceptance

The source owner is
`spine_cycle_sim/experiments/evaluation_impact/fullgraph_readiness/spine_resident/`:

- `preparation.py`: admit a clean committed host build with passing injected
  tests, full-capacity Release flags, explicit Xilinx runtime linkage, transitive
  headers, source hashes and unchanged fixed routed artifacts.
- `analysis.py`: require the leased BDF, exact workload, successful final
  validation, complete propagation, finite continuous wall time and one clean
  device ledger per round. Zero-round completion is allowed only with the
  benchmark's explicit final readback and final-state validation contract.
  The single exact `Using XCL_DEVICE_INDEX=0` or `=1` notice from the frozen
  `xcl2.cpp` is retained separately; all other nonempty stderr is rejected.
  This notice never substitutes for the host's leased-BDF check.
- `__main__.py`: thin freeze/run CLI. `board_protocol.py` names the separate
  Spine and G+R host contracts; `board_study.py` owns their shared execution.
- `board_access.py`: bounded waiting for the cooperative card lock. It never
  retries an error from an already-started FPGA operation or resets a card.
  A shared measurement lock serializes these matrices across both cards, so
  two hosts cannot compete for the fixed benchmark CPU pair. Compilation is
  still allowed concurrently within its independent memory budgets.

Two correctness smokes run first: the retained legacy host path, then the new
continuous benchmark. The matrix then runs AU/SU/WK/SO/PK/LJ/LJ08/R19 three
times, independently for SSSP, reciprocal CC and residual PageRank. Inputs and
sources come from the same complete 24-input offline manifest as G+R. The
six-partition G+R smoke does not prove cross-partition coverage for Spine's
different partition size; full-graph dimensions are checked separately.

SSSP/CC require exact final-state equality; residual PR uses the frozen
0.85 damping, 1e-6 activity threshold, 128-iteration old-rank preparation and
2e-5 final rank/residual tolerance. Insertion batches have eight physical edits,
except reciprocal CC with sixteen. FullPR, deletions/fallback, multi-batch
throughput and ten-stage calibration need separate experiments.

All dependencies and raw outputs remain pinned. Any smoke, runtime, final
oracle, ledger, timeout, source drift or memory-limit failure stops the matrix
and retains the attempted and unattempted rows. No partial speedup is promoted.
The success status explicitly excludes stage calibration and baseline matching.

## Memory And Reproduction

Each live matrix requires exactly 24 GiB hard/at most 22 GiB high, zero swap,
group OOM kill, two fixed CPUs and an atomic full-budget lease plus 32 GiB
system reserve. Safe bounded FPGA builds may continue concurrently. An idle,
healthy, exclusively leased U55C is required before programming; no board reset
or occupancy override is allowed. Each smoke is bounded to 600 seconds and
each large child to 1,800 seconds.

```bash
owner=spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.spine_resident
python3 -m "$owner" freeze \
  --spine /path/to/clean-spine-worktree \
  --build /path/to/passing-resident-host-tests \
  --artifacts /path/to/fixed-owner-fifo-artifacts \
  --output /path/to/fresh-freeze

# Run inside the containment/affinity described above. Omit --execute for a plan.
python3 -m "$owner" run \
  --preflight /path/to/passing-fullgraph-offline-attempt \
  --admission /path/to/fresh-freeze/results.json \
  --algorithm weighted_sssp --device 1 --repeats 3 \
  --output /path/to/fresh-board-attempt --execute
```

Read `results.json`, `raw/*.stdout.txt`, `raw/*.stderr.txt` and resource logs,
then check the service's terminal state. A passing freeze, mocked test or host
compile is not an FPGA result. Only completed admitted matrices can feed a
new hardware figure; original G/R performance controls remain separate gates.

## Current Evidence

Under `/data/chuxiao/experiments/baseline_hardware_validation_20261015/`,
`spine-resident-boundary-v1/host-tests-v5` passes four host compiles and three
injected-runtime tests at Spine commit `136cbac`. Earlier failed attempts are
retained. `spine-resident-freeze-v1/results.json` binds those binaries, their
source/header closure and all three fixed routed artifacts. Its decision is
`SPINE_RESIDENT_HOST_AND_FIXED_ARTIFACTS_PINNED_NOT_BOARD`.

The freeze itself proves preparation only. The separate SSSP v2 matrix below
has now completed FPGA execution; paired G+R results and final Fig7-11 remain
open. The original paper is unchanged.

The first board attempt, `spine-resident-sssp-board-v1`, ran the legacy smoke
successfully on BDF `0000:c1:00.1` and then failed the runner's stderr gate.
Its only stderr was the selection notice above. No new-mode smoke or large
case ran. This remains `FAILED_RETAINED`, not a completed matrix; the host,
bitstream, timing boundary and numerical results are unchanged for the retry.

### Completed SSSP Matrix

`spine-resident-sssp-board-v2/results.json` records both correctness smokes and
all eight full graphs with three independently restored repetitions: 26/26
executions pass, with no errors. Its SHA-256 is
`58abfaa670fd975d36e673190cc5fd6fedd210a7f4785aaea0cd16b786bab233`.
The status is
`SPINE_RESIDENT_BOARD_CONVERGENCE_PASS_NOT_BASELINE_OR_STAGE_CALIBRATION`.

| Graph | Resident wall median (ms) | Individual repetitions (ms) |
| --- | ---: | --- |
| AU | 123.501 | 127.694, 123.501, 120.321 |
| SU | 123.580 | 123.580, 121.730, 145.066 |
| WK | 95.3614 | 94.4134, 95.3614, 96.1479 |
| SO | 106.078 | 104.661, 106.408, 106.078 |
| PK | 127.058 | 127.058, 127.621, 124.124 |
| LJ | 185.846 | 187.173, 182.028, 185.846 |
| LJ08 | 155.098 | 139.359, 177.140, 155.098 |
| R19 | 122.516 | 122.556, 121.445, 122.516 |

These are continuous host-inclusive resident wall times, not kernel duration,
CPU setup-inclusive latency or paired speedups. The fixed bitstream runs at
150 MHz on leased BDF `0000:c1:00.1`; host affinity is CPUs 118/119. Systemd
unit `spine-resident-sssp-board-20261018-v2.service`, invocation
`5716557ced2f4228a7e79544b50a393d`, terminates successfully with main PID zero
and retained `active/exited` state. Its peak cgroup memory is 19,988,545,536
bytes; every recorded memory-limit/OOM event counter is zero.

An additional bounded offline replay independently reparses all 26 raw
stdout/stderr pairs and rechecks 626 dependency/evidence pins using the
[paired-report reader](../paired_board/README.md). Unit
`spine-sssp-report-replay-20261018-v1.service`, invocation
`b8da5f40e545414b9432606d397422b7`, exits zero and logs
`SSSP_RAW_REPLAY_PASS attempts=26 pins=626`. This is evidence replay, not
another FPGA measurement or stage calibration.

### Completed CC Matrix

`spine-resident-cc-board-v2/results.json` also completes both correctness
smokes and all 24 large runs: 26/26 pass, no errors. Its SHA-256 is
`81bae2a6bc20deeb90beeb0a412168e2a7cada131c29f3b89979aad61ad7ffa5`.
The status and boundary are the same as the SSSP matrix, not a paired ratio.

| Graph | Resident wall median (ms) | Individual repetitions (ms) |
| --- | ---: | --- |
| AU | 115.499 | 109.293, 117.093, 115.499 |
| SU | 91.6629 | 90.4834, 91.6629, 107.425 |
| WK | 132.294 | 126.731, 152.709, 132.294 |
| SO | 113.145 | 111.919, 113.145, 115.289 |
| PK | 86.7332 | 108.182, 86.7332, 84.2708 |
| LJ | 98.8597 | 104.577, 98.8597, 98.6983 |
| LJ08 | 100.084 | 99.653, 100.084, 102.257 |
| R19 | 176.380 | 175.798, 177.158, 176.380 |

Unit `spine-resident-cc-board-20261018-v2.service`, invocation
`ae84b6c8e821407cb0531e07b8c3525e`, terminates successfully with main PID
zero and retained `active/exited` state. Peak cgroup memory is 19,981,369,344
bytes and every recorded memory-limit/OOM event counter is zero. Board,
clock and CPU affinity match the SSSP protocol. The independent raw replay,
unit `spine-cc-report-replay-20261018-v1.service`, invocation
`3845e80b373448c0b3dfbfa798ad7aa1`, exits zero and logs
`CC_RAW_REPLAY_PASS attempts=26 pins=626` (peak 25,378,816 bytes).

### Completed Residual-PR Matrix

`spine-resident-respr-board-v2/results.json` completes both correctness
smokes and all 24 large runs: 26/26 pass, no errors. Its SHA-256 is
`159e1406eba89435c897b941d013a72c81f396aaad396e6fedbeaa87ef384bd3`.
The status and resident wall boundary are the same as the SSSP/CC matrices.

| Graph | Resident wall median (ms) | Individual repetitions (ms) |
| --- | ---: | --- |
| AU | 65.710 | 65.710, 67.3002, 65.5908 |
| SU | 64.854 | 64.854, 64.7275, 66.5302 |
| WK | 75.1713 | 74.9415, 75.1713, 75.9421 |
| SO | 228.359 | 226.847, 233.002, 228.359 |
| PK | 153.115 | 155.834, 153.115, 148.532 |
| LJ | 262.048 | 255.961, 263.081, 262.048 |
| LJ08 | 295.343 | 295.343, 302.407, 287.934 |
| R19 | 91.6909 | 92.0446, 91.6909, 87.9846 |

All eight large cases finish with zero propagation launches: the updated
residuals do not cross the frozen activity threshold. Maintenance, the host
degree/correction/seed work and final-state readback are still inside the wall
timer, and final reference validation passes. These cases do not demonstrate
large-graph residual propagation performance. The new-mode smoke does execute
one propagation round. Do not omit this distinction when interpreting ratios.

Unit `spine-resident-respr-board-20261018-v2.service`, invocation
`10d93ab3f64e4100bf5580623d9ba5c2`, exits zero, with `MainPID=0` and retained
`active/exited` state. Peak cgroup memory is 19,982,790,656 bytes; all recorded
memory-limit/OOM counters are zero. Independent raw replay reparses 26
stdout/stderr pairs and rechecks 626 pins. Its unit
`spine-respr-report-replay-20261018-v1.service`, invocation
`358e72900e264890a80d51418688e2fe`, exits zero; peak memory is 25,448,448 bytes.

FullPR has a separate
[convergence protocol](../fullpr_resident/README.md), not an extension of
these frozen runs. The G+R production routes, original-G/R controls, paired
ratios and replacement figures remain separate acceptance gates.
