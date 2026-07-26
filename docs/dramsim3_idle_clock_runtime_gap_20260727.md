# DRAMSim3 idle-clock runtime gap

Date: 2026-07-27

## Finding

Candidate10 uses one SST memHierarchy `MemController` plus one DRAMSim3 backend
per instantiated HBM pseudo-channel. The frozen Spine profile instantiates 23
reachable pseudo-channels. SST's memory controller can unregister its clock
when both its link and backend report idle, but the SST 16.0.0 DRAMSim3 backend
prevents that path:

```cpp
bool DRAMSim3Memory::clock(Cycle_t cycle) {
    memSystem->ClockTick();
    return false;
}
```

The backend therefore advances every instantiated controller every 1 ns even
when no request is queued. This agrees with the release-build audit: after the
cycle-core FIFO/AXI sleep fixes, long-run host time is dominated by valid
DRAMSim3 clock work rather than debug code or JSON output.

During the active 50,000-edge Full PageRank run, an epoch snapshot showed only
three controller instances completing reads/writes/activates while all 23
instances continued recording one million DRAM clocks and refresh/background
activity. This observation identifies host overhead; it does not authorize
removing architectural HBM channels or their energy.

## Unsafe shortcut

Changing `DRAMSim3Memory::clock()` to return `true` whenever its SST request map
is empty is not valid. While externally idle, DRAMSim3 still advances:

- refresh insertion and command timing;
- open-bank/precharge state;
- standby and refresh energy counters;
- the exact phase at which a future request arrives relative to refresh.

Stopping its clock without advancing those states can change first-request
latency, later backpressure, simulated cycles, and HBM energy. It would violate
the shared-memory comparison contract.

## Acceptable implementation direction

The safe optimization is an idle-interval API jointly implemented in the SST
backend and DRAMSim3. It may unregister the SST clock only after all requests,
return entries, and pending DRAM commands drain. On wake-up it must advance the
elapsed interval while preserving refresh phase, bank/rank state, timing
constraints, and every final power/statistics counter. A controller proven to
have no future request may use the same mechanism through simulation end, but
its idle/background energy must still be accumulated.

This is a host-runtime optimization only. It must not change the normalized
architecture profile, HBM channel map, simulated clock, request ordering, or
queue capacities.

## Acceptance criteria

1. Byte-identical result JSON after removing host wall time for Spine and
   GraSU+ReGraph across all three algorithms.
2. Identical cycles, request/response counts, bytes, ACT/PRE/row-hit counts,
   refresh counts, and final HBM energy on calibration and holdout workloads.
3. Boundary tests where a new request arrives immediately before, during, and
   after a refresh window.
4. No strict architecture ranking inversion across the frozen HBM sensitivity
   matrix.
5. Repeated host-wall improvement on the 4.78M-cycle residual workload, then a
   fresh 50,000-edge real-slice runtime-gate run.

Until these checks pass, the current always-clocked DRAMSim3 path remains the
publication baseline and the large-real runtime gate remains open or failed.
