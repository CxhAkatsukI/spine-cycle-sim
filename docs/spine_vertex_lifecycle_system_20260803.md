# Bounded Vertex Lifecycle in Persistent SSSP

## Contract

The graph keeps a fixed compile-time vertex domain. An ID below `MAX_N` may be
dormant or valid. Activation sets its validity bit. Deactivation clears the bit
only after every incident edge has been retired or masked; otherwise the
operation is rejected without changing state.

The paper-aligned SSSP system uses a separate AXI initiator on pseudo-channel
22, sharing arbitration with the compute active bitmap. Its validity bitmap is
placed in an aligned non-overlapping address region, so no additional HBM
pseudo-channel is consumed.

Every lifecycle change performs a timed 8-byte HBM bitmap read. A changed bit
also performs an 8-byte write. Existing-state requests are timed read-only
no-ops. The request and response ledger must close before another graph
transaction begins.

## System Behavior

When enabled, `SpineVerticalSliceSystem`:

- rejects an initial graph containing an invalid endpoint;
- rejects an incremental update or rebuild containing an invalid endpoint;
- rejects an invalid source in the owner frontier;
- permits lifecycle operations only between drained graph transactions; and
- requires a quiescent owner ledger before changing validity.

The integrated test starts with an eight-ID fixed domain and four valid IDs. It
activates dormant ID 6 through HBM, inserts edge `0 -> 6`, and obtains SSSP
distance 2. It then rebuilds without that incident edge, deactivates ID 6, and
proves that a later update referencing ID 6 is rejected.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-architecture-alignment
cmake -S . -B /tmp/spine-cycle-sim-owner-build -DBUILD_TESTING=ON
cmake --build /tmp/spine-cycle-sim-owner-build -j4
/tmp/spine-cycle-sim-owner-build/cpp/spine_cycle_core_tests \
  spine_vertex_lifecycle_system
/tmp/spine-cycle-sim-owner-build/cpp/spine_vertex_lifecycle_tests
```

## Evidence Boundary

This proves SSSP simulator semantics and shared-channel traffic. It does not
yet prove a matching HLS controller, routed timing, or lifecycle integration in
CC and PageRank. Per-edge validity lookups are not charged: safe deactivation
requires incident edges to be absent or masked before publication, while the
timed bitmap controls transaction admission.
