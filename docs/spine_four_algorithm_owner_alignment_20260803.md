# Spine four-algorithm owner alignment

Date: 2026-08-03

## Scope

This checkpoint extends the frozen paper-architecture owner protocol from the
specialized weighted-SSSP pipeline to the shared Map/Reduce/Apply pipeline used
by connected components (CC), thresholded residual PageRank, and full
PageRank. It does not change graph maintenance, the HBM channel map, the
algorithm arithmetic, or the public behavior when owner scheduling is not
enabled.

The implementation follows the contract in
`configs/contracts/spine_paper_architecture_alignment_v1.json`:

- device-owned `queued`, `in_flight`, and `dirty` state;
- bounded owner and reactivation FIFOs;
- lossless reactivation while a key is in flight;
- work credits created at activation and retired at completion;
- host relaunch/re-binning may transport an already selected frontier, but may
  not recompute frontier membership;
- convergence requires an empty frontier and a closed, quiescent owner ledger.

## Execution protocol

`SpineOwnerFrontierController` owns the round boundary.

1. On the first round, it admits each frontier key through
   `SpineOwnerScheduler::try_activate` and dispatches the published keys.
2. Reader and compute remain behind the same ready gate until the owner has
   dispatched the complete frontier and any device seed/correction writer has
   finished its HBM output.
3. During Map/Reduce/Apply, an active apply result must acquire owner admission
   before the apply response can leave its finite response FIFO. Owner
   backpressure therefore stalls the real compute path.
4. At a relaunch boundary, the controller completes the prior in-flight
   frontier. The owner requeues dirty keys and publishes the already selected
   next frontier. The controller verifies that the dispatched key set exactly
   matches the device-produced active list.
5. The final frontier is explicitly completed even though no new kernel launch
   follows. A run is reported converged only when the work-credit ledger is
   closed and the owner is quiescent.

Full PageRank uses the same protocol with a dense-frontier rule: every vertex
is explicitly readmitted for the next iteration. CC and residual PageRank use
only device-produced active vertices. Weighted SSSP retains its tile-optimized
compute path and the equivalent owner protocol added in commit `d7cdea9`.

## Vertex lifecycle

The PageRank/CC system can also instantiate the bounded HBM-backed validity
bitmap used by SSSP. Initial graph endpoints and each frontier are checked
against it. Activation and safe deactivation issue timed bitmap
read-modify-write transactions; deactivation still requires incident edges to
have been retired or masked and an owner-quiescent system.

## Reproduction

```bash
cmake -S . -B /tmp/spine-cycle-sim-architecture-build \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build /tmp/spine-cycle-sim-architecture-build -j 8
ctest --test-dir /tmp/spine-cycle-sim-architecture-build --output-on-failure
```

Targeted checks are available through the core-test filter:

```bash
/tmp/spine-cycle-sim-architecture-build/cpp/spine_cycle_core_tests \
  spine_cc_device_owner
/tmp/spine-cycle-sim-architecture-build/cpp/spine_cycle_core_tests \
  spine_residual_device_owner
/tmp/spine-cycle-sim-architecture-build/cpp/spine_cycle_core_tests \
  spine_full_pr_dense_owner
```

The fixtures intentionally use one-entry owner and reactivation FIFOs. They
check the independent algorithm oracle, apply-response backpressure,
activation conservation, work-credit closure, and final quiescence. The CC
fixture additionally exercises a timed safe vertex deactivation.

## Evidence boundary

This checkpoint establishes execution-driven owner/lifecycle behavior for all
four simulator algorithms. The scheduler state transitions, finite owner and
reactivation FIFOs, apply-response backpressure, and credit-based quiescence
are explicit cycle-level components. They are not, however, an admitted
absolute-cycle model of the aligned HLS owner implementation.

The distinction is the owner-state storage path. The HLS implementation stores
the `queued`, `in_flight`, `dirty`, and validity bitmaps in HBM pseudo-channel
22. It performs first-use bitmap initialization and bitmap-word
read-modify-write operations through the corresponding AXI master. The current
C++ owner scheduler keeps those logical bits in simulator-owned state and does
not emit the matching owner-state AXI transactions. Its FIFO stalls and
evaluate/commit ordering are real, but its control-cycle total omits that HBM
traffic and contention.

Consequently:

- the aligned simulator is valid for owner-protocol correctness, boundedness,
  backpressure, and work-conservation evidence;
- routed and direct-FPGA HLS runs establish implementation feasibility and
  hardware correctness independently;
- CC/PageRank owner-path absolute cycles must not be called FPGA-calibrated
  until a memory-backed owner model is admitted against matching hardware; and
- the native refactor31 transfer calibration is unaffected because its frozen
  profile explicitly disables the complete owner scheduler and remains a
  separate calibration baseline.

## Physical implementation evidence

The matching HLS branch `codex/paper-owner-fifos` now has four independently
routed, policy-specialized three-CU systems at the common 150 MHz target. SSSP,
CC, thresholded Residual PageRank, and Full PageRank each pass direct U55C tiny
and 19,399-vertex/50,000-edge Amazon-slice checks against an independent CPU
oracle. The Full PageRank run is a useful boundedness witness: its 256-entry
reactivation FIFO reaches full occupancy and backpressures the compute path
without losing work.

The fail-closed routed manifests are:

```text
paper_owner_fifo_sssp_routed_v1.json
paper_owner_fifo_cc_routed_v1.json
paper_owner_fifo_respr_routed_v1.json
paper_owner_fifo_fullpr_routed_v1.json
```

They live in the HLS repository under `docs/evidence/`. This closes
algorithm-specific functional feasibility, finite-FIFO backpressure, routed
setup/hold, resource, lifecycle, and direct-board evidence. It does not convert
the aligned simulator's owner-path cycles into FPGA-calibrated performance;
that still requires a matching memory-backed timing transfer experiment.
