# Independent FullPR Resident Protocol

## Scope

The existing eight-graph SSSP/CC/ResPR host and runner remain frozen. This
separate protocol adds true FullPR convergence; neither the legacy fixed-three-
sweep host nor the compact FullPR results admit it.

The predeclared first cohort is AU, SU and WK, using their complete directed
`weighted_sssp_insert_u8.graph` inputs from the existing 24-input manifest.
Vertex IDs and eight insertion edits are unchanged; PageRank ignores weights.
This is three complete inputs, not eight graphs or a compacted-ID slice.
Before those inputs, a four-vertex cycle with a dangling vertex and one
insertion must converge in more than three sweeps. This catches accidental
reuse of the old fixed-round benchmark. A failed smoke stops the entire run.

Both arms use old-graph converged ranks, 0.85 damping, global dangling-mass
redistribution and global L1 delta at most `1e-6`, with a 256-sweep limit.
Old ranks are prepared by 128 CPU sweeps and independently checked for the
same fixed-point tolerance. Final CPU reference validation requires finite
nonnegative ranks, exact degrees, per-vertex error at most `2e-5`, total rank
error at most `2e-4`, and rank-mass error at most `1e-3`. Failure is not a
timeout projection or permission to relax the numerical criterion.

## Timing And Ownership

The continuous resident wall boundary is the same as the differential matrix:
old state and batch resident, through maintenance and convergence, to final
readback, including actual host relaunch. Programming, initial preload and
final reference validation are outside. The fixed Spine FullPR kernel reads
a separate degree bank; its post-maintenance CPU degree preparation and state
upload are explicitly inside the timer. Each sweep's full-state readback is
also counted. This is not an all-device or CPU-setup-inclusive claim.

The code owner is `fullgraph_readiness/fullpr_resident/`:

- `inputs.py` freezes the predeclared cohort and smoke without changing inputs.
- `spine.py` admits the clean FullPR host build, transitive dependencies,
  injected-runtime test and fixed 150-MHz routed artifact, then checks every
  FullPR device ledger and convergence record.
- `gr_preparation.py` reuses the bounded offline compiler/preparation executor
  with one FullPR binary, the dangling smoke and the exact AU/SU/WK cohort.
  It checks CPU-reference convergence, PMA layout and update conservation;
  this cannot program a card or establish performance.
- `gr.py` replays those raw preparations, verifies the host-only fork has
  identical kernels and headers to the routed production revision, and admits
  only the new FullPR routed artifact. Each sweep, first convergence, final
  CPU error, probability mass and complete event trace must pass independently.
- `__main__.py` is a thin CLI. Execution reuses `board_study.py` and its card
  and measurement locks, exactly two CPUs, 24-GiB hard/22-GiB high limit,
  zero swap, full-budget atomic admission and 32-GiB system reserve.
- `continuation.py` waits for one exact FullPR return-service invocation,
  replays the hash-pinned offline report, checks its returned admission and
  runs only this protocol. Three repetitions and the smoke are mandatory;
  producer drift, board failure or pin changes stop the run without retry.

The source branches are Spine `codex/fullpr-resident-convergence` at
`6728171` and G+R `codex/fullpr-resident-convergence` at `6eb197a`.
Both are committed and pushed. The isolated G+R host option is
`--resident-fullpr`; it rejects residual-PR and update-only combinations.
It has a CPU-only independent reference test, not an FPGA validation.
The G+R board protocol is implemented but its real execution must wait for
successful frozen preparation and the new FullPR production route admission.
Its own pass is neither a paired FullPR report nor a publication match.
No old FullPR result is reused as a converged paired speedup.

## Reproduction And Current Evidence

Run preparation in a bounded offboard scope, with a fresh destination each
time. Replace the example paths with the frozen campaign paths:

```bash
owner=spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.fullpr_resident
python3 -m "$owner" inputs --manifest /campaign/manifest.json --output /campaign/fullpr-inputs
python3 -m "$owner" freeze-spine --source /clean/fullpr-spine \
  --build /campaign/clean-host-tests/build --artifacts /fixed-owner-fifo-artifacts \
  --output /campaign/fullpr-spine-freeze

# Inside the required containment/affinity; omit --execute for a plan only.
python3 -m "$owner" run-spine --preflight /campaign/fullpr-inputs \
  --admission /campaign/fullpr-spine-freeze/results.json --device 1 --repeats 3 \
  --output /campaign/fullpr-spine-board --execute

# Same offline 24-GiB hard/22-GiB high, zero-swap scope and 32-GiB reserve.
python3 -m "$owner" prepare-gr --source /clean/fullpr-gr \
  --cohort /campaign/fullpr-inputs --xrt /opt/xilinx/xrt \
  --hls /data/yxx/tools/xilinx/Vitis_HLS/2024.1 \
  --output /campaign/fullpr-gr-preparation

# Inside the board scope above; omit --execute for a plan only.
python3 -m "$owner" run-gr --preflight /campaign/fullpr-gr-preparation \
  --admission /campaign/new-production-fullpr-admission/summary.json \
  --device 1 --repeats 3 --output /campaign/fullpr-gr-board --execute

# Alternatively wait for one exact return, in the same bounded board scope.
python3 -m "$owner.continuation" \
  --preflight /campaign/fullpr-gr-preparation \
  --preflight-sha256 EXACT_OFFLINE_REPORT_SHA256 \
  --returned /campaign/fullpr-return \
  --admission /campaign/fullpr-return/admission/summary.json \
  --unit exact-fullpr-return.service --invocation EXACT_INVOCATION_ID \
  --device 1 --output /campaign/fresh-fullpr-continuation
```

Under `/data/chuxiao/experiments/baseline_hardware_validation_20261015/`,
`fullpr-resident-host-v4/build` passes all four host builds and injected tests
at the clean Spine commit above. Unit
`spine-fullpr-resident-host-tests-20261018-v4.service`, invocation
`b3139d09453b46339ccf8ac02ea31a88`, exits zero; peak cgroup memory is
523,960,320 bytes. `gr-fullpr-resident-host-v2` passes four host builds,
the CPU reference test and prepare-only positive/negative cases at the clean
G+R commit. Its unit `gr-fullpr-resident-host-tests-20261018-v2.service`
exits zero, peak memory 345,423,872 bytes. These are offboard gates only;
earlier dirty and failed attempts are retained.

Read `results.json` and every raw stdout/stderr/resource record, then attest
the service's terminal state. A successful freeze, compile, CPU test or
mocked protocol test is not a measured FullPR result.

The G+R parser keeps the last sweep's L1 delta (the stopping criterion)
separate from the final CPU-reference L1 error (the correctness check).
Event spans include overlap and stalls; they are not exclusive ten-stage
counters. Unit tests use synthetic logs and mocked execution, including
failure, missing-event and premature-convergence cases. They do not validate
the hardware datapath or resolve the Spine failures below.

The continuation's success is only the new-G+R FullPR arm. In particular,
it cannot promote a failed Spine artifact or create a paired FullPR speedup.
Its tests use mocked services and board execution, not hardware measurements.

### Complete G+R Offline Preparation

`gr-fullpr-preparation-v2` completes compilation, the dangling smoke and all
three AU/SU/WK preparations: five child steps, zero errors and zero OOM
events. Its service is `gr-fullpr-preparation-20261018-v2.service`, invocation
`8f7f4612dde8464ba898b1832c6639b5`, with peak memory 825,266,176 bytes and
zero exit status. The terminal report SHA-256 is
`c13ce477b191d0bfbe7cd31add6b2357af27fc383d1429388cd5e1a0da78c52e`.
Independent raw-log replay verifies the pinned host-only source `6eb197a`.
AU/SU/WK use 8/9/18 destination partitions and respectively 1,843,296 /
2,625,456 / 2,727,664 physical PMA slots. This is
`GR_FULLPR_HOST_PREPARATION_PASS_NOT_BOARD_OR_PERFORMANCE`, not hardware
convergence. V1 failed at startup before runner extraction had completed;
its separate failed service and startup journal remain retained.

## Retained FPGA Failures

Two subsequent board attempts are `FAILED_RETAINED`, not accepted FullPR
matrices. Both use the unchanged fixed FullPR bitstream on BDF `0000:c1:00.1`.

- `spine-fullpr-resident-board-v1`: the dangling smoke passes in 27 sweeps,
  with resident wall 912.025 ms and last L1 delta `9.53674e-7`. AU fails at
  sweep zero because the full-domain frontier is missing. The host then
  stopped before printing its device ledger. Unit
  `spine-fullpr-resident-board-20261018-v1.service`, invocation
  `d65fcdd87aa94b5b8c446430bc8f3f6a`, exits one; peak memory 2,450,759,680 bytes.
- `spine-fullpr-resident-board-v2`: an isolated diagnostic host at clean,
  pushed Spine commit `bec812be1ae1aecde9936753c4d5e4bd83e3ab2e` prints the
  failed ledger before rejecting the frontier. It changes neither successful
  arithmetic nor the bitstream or timing boundary. This attempt already fails
  its smoke at sweep zero: expected frontier 4, returned 0, `overflow=1`,
  reactivation FIFO backpressure 4 and maximum occupancy 256. Task, source
  and owner status fields are zero. Unit
  `spine-fullpr-resident-board-20261018-v2.service`, invocation
  `243fbab298a14d869e26020ebe0ca5e3`, exits one, `MainPID=0`; peak memory
  2,326,892,544 bytes. No large case was launched.

The v2 diagnostic build passes four host builds and injected tests under
`fullpr-resident-host-v5/build`; the corresponding freeze is
`fullpr-spine-host-freeze-v2/results.json`. Unit
`spine-fullpr-resident-host-tests-20261018-v5.service`, invocation
`9f6ca96b17804da6ab1b5cee4b9dd96a`, exits zero; peak memory 525,635,584 bytes.
These tests validate diagnostic ordering, not the failed hardware datapath.

An independent read-only source/XO review finds a concrete mismatch: the
source unconditionally resets both static owner/reactivation FIFOs on entry,
but the packaged FullPR RTL has no entry writer for their head/tail/count
metadata. The synthesized depth-16 metadata RAMs load zeros at configuration;
their reset input does not clear the RAM at kernel invocation. Head/count
write enables select apply/drain, and tail write enables select enqueue.
Configuration initialization is not invocation initialization.

The v2 ledger is consistent with a reactivation count initially at 256:
reserve drains four entries, enqueue restores the count, then final drain
cannot publish 256 entries into a four-entry frontier and returns overflow.
This is an explanatory hypothesis for that failure, not a measured initial
count. Missing reset is a source/RTL defect and failed-invocation recovery
risk. Successful drains can empty the FIFO, so it does not by itself explain
the original v1 AU failure. V1 lacks the failure ledger; exact reconfiguration
and high-pressure writeback remain unverified. No kernel fix is claimed.

The reviewed XO is `spine_partconv_compute_kernel.fullpr.hw.xo` under
`/data/feiyang/codex_builds/spine_paper_alignment/owner_fifo_hw_v1/fullpr/xclbin/`.
Inside `hdl/verilog/`, the long-named `partitioned_run_pagerank_compute_3_s.v`
module's metadata write muxes are at lines 8819--8977; sibling
`partitioned_owner_activate_word.v` tail write enables are at lines
5280--5285 and 5380--5385. These module names have the common
`spine_partconv_compute_kernel_` prefix. Source calls are in
`src/spine_pagerank_compute.hpp` at line 148, with reset implementation in
`src/spine_owner_state.hpp` at line 139 of the pinned diagnostic worktree.

A prospective fix must prove all metadata slots clear before first use,
exercise wrap/reserve and a failed drain followed by another invocation,
and rerun emulation and clean-start hardware correctness. It must not merely
add a pragma and assume synthesis preserved the reset. Do not relax
the full-frontier or overflow checks, reset the board without admission, or
retry until a passing sample appears. The isolated passing smoke is not a
paired performance result. No accepted FullPR matrix, paired speedup, stage
calibration, publication match or finalized figure is claimed.
