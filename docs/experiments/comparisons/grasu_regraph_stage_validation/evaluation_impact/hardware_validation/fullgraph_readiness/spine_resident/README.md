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

This evidence currently proves preparation only. New-mode FPGA smokes, the
complete repeated matrix, paired G+R results and final Fig7-11 are not accepted
by the freeze. The original paper is unchanged.
