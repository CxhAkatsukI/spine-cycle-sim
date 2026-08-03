# Device-Owned SSSP Scheduling

## Scope

The paper-alignment profile now connects device-generated SSSP activations to
an execution-driven owner scheduler. Native and previously reported profiles
remain unchanged unless `SpineOwnerSchedulerConfig` is passed to
`SpineVerticalSliceSystem`.

Each key has sparse `queued`, `in_flight`, and `dirty` state. A successful
activation creates one work credit. A completion retires one credit. An update
to an in-flight key creates a second credit and preserves a deferred
reactivation; duplicate queued or dirty activations coalesce without losing the
existing credit.

The physical storage path is bounded:

- one finite owner ingress FIFO per partition;
- one finite reactivation ingress FIFO per partition;
- a device-published active list bounded by the fixed vertex domain;
- a deferred-reactivation list bounded by the same partition domain; and
- the existing AXI/HBM active-output writes, which must drain before relaunch.

The ready and deferred lists bridge the current round-relaunch HLS interface.
They do not let the host recompute membership. The host may re-bin and relaunch
device-produced IDs, matching the frozen contract and current paper text.

## Critical-Path Integration

`SpineSplitSsspCompute` handshakes each active-output record with the owner
scheduler before enqueueing its AXI write. A full owner or reactivation FIFO
stalls active emission and therefore backpressures the compute state machine.
The handshake is part of evaluate/commit ordering; it is not post-run
accounting.

At a round boundary, the system:

1. retires the exact in-flight input frontier;
2. preserves and republishes dirty reactivations;
3. dispatches exactly the device-generated next frontier; and
4. declares convergence only when work credits are zero and all modeled
   AXI/FIFO paths are drained.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-architecture-alignment
cmake -S . -B /tmp/spine-cycle-sim-owner-build -DBUILD_TESTING=ON
cmake --build /tmp/spine-cycle-sim-owner-build -j4
/tmp/spine-cycle-sim-owner-build/cpp/spine_cycle_core_tests \
  spine_device_owner_multiround
ctest --test-dir /tmp/spine-cycle-sim-owner-build --output-on-failure
python3 -m unittest discover -s tests
```

The weighted chain/shortcut test executes six rounds. It creates and retires
11 work credits, closes the owner ledger, reaches quiescence, and produces the
oracle distances `[0, 3, 2, 7, 8, 10]`. With one-entry owner and reactivation
FIFOs, the first round observes a real owner backpressure cycle and resumes
without dropping an activation.

## Evidence Boundary

This checkpoint proves integrated SSSP simulator behavior. It does not yet
prove:

- cycle calibration of owner-control overhead against FPGA;
- the owner state machine in HLS or a routed xclbin;
- integration with CC, Residual PageRank, or Full PageRank; or
- a fully asynchronous no-relaunch execution engine.

Those items remain required before replacing the frozen evaluation baseline.
