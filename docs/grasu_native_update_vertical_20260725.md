# GraSU Native PMA Update Vertical Slice

Date: 2026-07-25

## Result

The fine-grained C++ core now executes the current U55C GraSU update path. It
does not mutate a logical graph and then estimate time. Updates are loaded from
payload-backed HBM and must pass through real simulator components:

```text
4 update AXI ports
-> 4 serial direct binary-search CUs
-> 4 finite AXIS links
-> fixed-order dispatch
-> 2 direct-cache or 2 DDR process CUs
-> 512-bit PMA AXI read-modify-write
```

All AXI masters share the same `MemoryBackend` used by Spine. Separate masters
mapped to one pseudo-channel therefore contend online. Registered FIFO pushes
are visible on the next cycle and full queues propagate backpressure.

## Version Mapping

This model follows the actual integration xclbin flags, not the unused wider
branch in the source:

- `GRASU_COMPACT_HBM_PORTS`: each of four `bin_search` CUs uses the serial
  `bin_search_direct` path.
- `GRASU_PURE_PIPELINE_DIRECT_CACHE`: each of two cache CUs performs one
  ordered HBM segment RMW at a time.
- Each of two DDR CUs retains two halves and 16 lanes per half. A lane is
  single-flight, so consecutive updates to one segment cannot read stale PMA
  state.

The original 64-worker BIPA search and 16-bank URAM cache are not native U55C
behavior. They remain available only as future projected features.

## PMA Payload

The host-style layout builder reserves the union of initial edges and future
insertions. Each source row is rounded to 16 slots. Binary heads are generated
before non-live reservations are replaced by `0x80000000`, matching the GraSU
preprocessing order.

Even and odd global segments are striped across the same four PMA images as
the host code. The cache region is authoritative in HBM channels 0 and 2; the
DDR region is authoritative in channels 1 and 3. Both are addressed by local
`global_segment / 2` indices.

An insertion outside the reserved PMA universe and a deletion of a non-live
edge are rejected as workload-contract errors. This prevents the simulator
from silently modeling dynamic capacity that the hardware does not have.

## Evidence

The route/correctness test uses ten ordered updates, deliberately crossing:

- cache and DDR regions;
- even and odd PMA segment placement;
- insertion and deletion;
- multiple sequential updates to one segment;
- rows requiring more than one binary-head probe.

Result:

```text
cycles at 200 MHz: 176
updates:            10 (9 insert, 1 delete)
cache / DDR:        5 / 5
binary probes:      13
HBM read bytes:     904
HBM write bytes:    640
final PMA oracle:   PASS
```

The read ledger is exact for the modeled path:

```text
10 update records * 8 B
+ 10 row records * 8 B
+ 13 binary heads * 8 B
+ 10 PMA segments * 64 B
= 904 B
```

Every update also writes one complete 64-byte PMA segment.

A separate 128-update pressure case sets the backend to one outstanding request
per channel. It completes with exact payload and records:

```text
cycles at 200 MHz:      1238
AXI backend stalls:       28
AXIS push stalls:        3097
lane queue stalls:       2078
final PMA oracle:        PASS
```

These pressure values prove online contention and backpressure behavior. They
are not U55C-calibrated parameters.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
cmake -S . -B build/cycle-core -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/cycle-core
./build/cycle-core/cpp/grasu_cycle_tests
ctest --test-dir build/cycle-core --output-on-failure
```

## Remaining Boundary

This milestone validates GraSU update structure and payload correctness on the
mock backend. It does not yet include SST-HBM, hardware-cycle calibration,
host vertex reorder/PMA construction time, or ReGraph compute. The next
vertical slice must attach a PMA-native row/segment reader and the shared
Map/Reduce policy without creating a compact edge-array copy.
