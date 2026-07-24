# GraSU + PMA-Native ReGraph SSSP Vertical Slice

Date: 2026-07-25

## Result

The normalized comparator now executes one complete dynamic-graph path:

```text
GraSU ordered PMA updates
-> payload-backed 512-bit PMA
-> completion barrier
-> PMA-native ReGraph reader
-> finite 8-edge AXIS batches
-> 8-bank gather and partition sweeps
-> HBM-backed ReGraph apply
-> next active superstep or completion
```

There is no PMA-to-compact-edge-array copy. The compute model is not allowed to
inspect PMA payload while running. Row metadata, source state, and PMA segments
enter the compute path only through `FixedAxiPort` responses from the shared
`MemoryBackend`. The final distance check reads the committed vertex-state
payload after the timed execution has drained.

This implements the PMA-native boundary proposed for the `normalized` design
in `docs/grasu_regraph_pma_native_contract_20260725.md`. The microbenchmarks in
this document are component validation at 200 MHz with the source-shaped eight
ReGraph lanes. They are not normalized comparison results: the current
`grasu_regraph_normalized_spine23` profile specifies 150 MHz and four lanes.
They are also not native hardware evidence until a matching PMA reader is
implemented and synthesized.

## Implemented Structure

- Source state is loaded in configurable 4096-word chunks, matching the
  integration build's `SRC_BUFFER_SIZE=4096` shape. The 16-vertex functional
  case therefore performs one aligned 64-byte refill per superstep rather than
  waiting on one HBM transaction per source.
- Every source reads its 64-bit PMA row bounds. Every reserved 16-slot segment
  is read as one 64-byte request, including empty capacity.
- A segment produces `16 / edge_lanes` registered batches. The source-shaped
  validation uses eight lanes; the target normalized profile can use four.
  The finite AXIS FIFO backpressures the reader while gather reset or bank work
  cannot consume.
- Gather has eight destination banks. It counts extra cycles when destinations
  in one batch collide on a bank. Reduction semantics use the shared
  `GraphAlgorithmPolicy` weighted-SSSP Map/Reduce operations.
- Each superstep charges a full gather reset and merge sweep. The native
  profile processes two vertices per cycle in each sweep.
- Apply reads and writes all 65536 destination words as 64-byte bursts under
  the native profile, sets the ReGraph active bit for improved vertices, and
  drives the next superstep.
- Update and compute are serial with an explicit completion barrier.

GraSU PMA slots currently encode only a 32-bit destination. The PMA-native
vertical slice therefore assigns every edge weight 1. It validates the SSSP
Map/Reduce machinery and ReGraph active-frontier behavior, but it is not yet a
general weighted-input comparator.

## Functional Evidence

The test begins with six edges, applies two insertions and one deletion through
the execution-driven GraSU update system, and then starts SSSP at vertex 0.
The expected distances are computed independently from the final edge set.

```text
cycles at 200 MHz:  1205
supersteps:            4
PMA segments read:    20
PMA slots scanned:   320
live edges scanned:   28
active edges mapped:   7
HBM read bytes:      2304
HBM write bytes:      256
distance oracle:     PASS
```

The four supersteps each scan five reserved segments. Thus 320 slots are
visited even though only seven live edges exist. This exposes PMA density as a
first-class performance variable.

The read ledger is:

```text
64 row records * 8 B       =  512 B
4 source-cache refills     =  256 B
20 PMA segments * 64 B     = 1280 B
4 apply reads * 64 B       =  256 B
total                      = 2304 B
```

Apply writes one 64-byte state burst in each superstep.

## Native Partition Evidence

A one-edge, 16-vertex graph is also run with the source-shaped ReGraph
`PARTITION_SIZE=65536` setting:

```text
cycles at 200 MHz:       311307
supersteps:                   2
gather reset + merge:    131072 cycles
apply reads:                8192 x 64 B
apply writes:               8192 x 64 B
distance oracle:              PASS
```

The graph is tiny, but ReGraph still sweeps the whole destination partition.
This fixed cost is why a small-batch comparison must preserve partition shape;
using a 16-word apply in performance experiments would hide the comparator's
dominant overhead.

## Contention Evidence

A 128-edge fanout uses one outstanding backend request per HBM channel and a
one-entry AXIS FIFO:

```text
cycles at 200 MHz:       9813
AXI backend stalls:       396
AXIS push stalls:          16
distance oracle:         PASS
```

These counts prove that PMA traffic, row traffic, and finite queues participate
in online execution and backpressure. They are not calibrated U55C latency
values because this test uses `MockMemoryBackend`.

## Four-Lane Parameter Evidence

A separate 150-MHz smoke case sets `edge_lanes=4` and `gather_banks=4`, as
required by the current normalized profile. One 16-slot PMA segment becomes
four registered batches rather than two:

```text
cycles at 150 MHz:  503
supersteps:           2
PMA segment reads:    2
four-lane batches:    8
distance oracle:   PASS
```

This proves that lane count changes executed queue/gather work. It is still a
component smoke test on `MockMemoryBackend`, not the complete normalized
profile run.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
cmake -S . -B build/cycle-core -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/cycle-core
./build/cycle-core/cpp/grasu_cycle_tests
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
```

Regenerate the figure with:

```bash
dot -Tsvg docs/figures/grasu_regraph_pma_native_sssp.dot \
  -o docs/figures/grasu_regraph_pma_native_sssp.svg
```

## Remaining Boundary

1. Run this vertical slice on `SstMemoryBackend` with a pinned HBM profile and
   report wall-clock simulation throughput.
2. Wire the now-configurable reader/gather lane count into a profile-driven
   runner and execute the complete pinned 150-MHz/four-lane normalized profile
   separately from the 200-MHz/eight-lane source-shaped validation profile.
3. Replace ideal immediate gather forwarding with an explicit six-stage RAW
   bypass/register model and attach operation/queue activity to energy events.
4. Extend the PMA contract for real edge weights before claiming weighted SSSP
   equivalence with Spine.
5. Add full PageRank and thresholded residual PageRank iteration controllers
   on the same PMA reader, gather, apply, and algorithm-policy interface.
6. Implement and synthesize the matching PMA-native HLS reader. Until then,
   normalized PMA-native cycles are simulator results, not measured hardware.
7. Add graph ingestion, batch manifests, dual update/algorithm oracles,
   GraSU-versus-Spine reports, SST-HBM sweeps, and PPA/energy accounting.
