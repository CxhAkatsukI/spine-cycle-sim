# GraSU + PMA-Native ReGraph SSSP Vertical Slice

> Historical unit-weight milestone. The weighted PMA closure is documented in
> `grasu_regraph_weighted_dynamic_sssp_20260725.md`.

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

- Source state is loaded through the HLS request/response protocol in fixed
  4096-word windows. The reader keeps two ping-pong buffers, requests up to one
  window ahead, and waits until the next window starts arriving before it uses
  the current one. Every request transfers 256 64-byte lines even for a tiny
  graph.
- Every source reads its 64-bit PMA row bounds. Every reserved 16-slot segment
  is read as one 64-byte request, including empty capacity.
- A segment produces `16 / edge_lanes` registered batches. The source-shaped
  validation uses eight lanes; the target normalized profile can use four.
  The finite AXIS FIFO backpressures the reader while gather reset or bank work
  cannot consume.
- Gather has configurable lane-local destination banks: eight in source-shaped
  component tests and four in the normalized profile. Lane `u` always accesses
  bank `u`; there is no `destination % bank` arbitration. Each bank has the HLS
  `L+1` forwarding history for six-cycle URAM RAW hazards. Reduction semantics
  use the shared `GraphAlgorithmPolicy` weighted-SSSP Map/Reduce operations.
- The first superstep charges a full gather reset. Every superstep charges the
  output/clear sweep, which leaves the URAM ready for the next superstep. This
  follows the host's `reset_tmp_prop = (super_step == 0)` protocol. The native
  profile processes two vertices per cycle in each sweep.
- Gather output is a finite stream of 64-bit rows. A free-running merger packs
  eight rows into one 512-bit Apply burst. Depth-16 registered FIFOs connect
  gather to merger, merger to Apply, and Apply to the HBM wrapper.
- Apply reads and writes all 65536 destination words as 64-byte bursts under
  the native profile, sets the ReGraph active bit for improved vertices, and
  drives the next superstep. Each output burst is committed to local state on
  HBM[30] and mirrored to ping-pong source state on HBM[1] and HBM[3].
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
cycles at 200 MHz:  3721
supersteps:            4
PMA segments read:    20
PMA slots scanned:   320
live edges scanned:   28
active edges mapped:   7
HBM read bytes:    133120
HBM write bytes:      768
distance oracle:     PASS
```

The four supersteps each scan five reserved segments. Thus 320 slots are
visited even though only seven live edges exist. This exposes PMA density as a
first-class performance variable.

The read ledger is:

```text
64 row records * 8 B       =    512 B
8 source windows * 16384 B = 131072 B
20 PMA segments * 64 B     =   1280 B
4 apply reads * 64 B       =    256 B
total                      = 133120 B
```

Apply produces one 64-byte state burst in each superstep. The modeled hardware
topology writes that burst three times: local apply state plus two source-state
copies.

## Native Partition Evidence

A one-edge, 16-vertex graph is also run with the source-shaped ReGraph
`PARTITION_SIZE=65536` setting:

```text
cycles at 200 MHz:        99257
supersteps:                   2
gather reset + merge:     98304 cycles (32768 + 65536)
apply reads:                8192 x 64 B
apply writes:               8192 x 64 B
source-state writes:       16384 x 64 B
max read / write in-flight:    2 / 2
max apply pipeline occupancy:      14
max merger FIFO occupancy:          1
max wrapper pipeline occupancy:     9
distance oracle:              PASS
```

The graph is tiny, but ReGraph still sweeps the whole destination partition.
This fixed cost is why a small-batch comparison must preserve partition shape;
using a 16-word apply in performance experiments would hide the comparator's
dominant overhead. The fixed source-window traffic is mostly hidden by this
sweep, while explicit streams let Apply and wrapper overlap gather output.

## Contention Evidence

A 128-edge fanout uses one outstanding backend request per HBM channel and a
one-entry AXIS FIFO:

```text
cycles at 200 MHz:      15037
AXI backend stalls:      8534
AXIS push stalls:        2864
gather output stalls:    1482
merger output stalls:    1366
apply output stalls:      416
wrapper pipeline stalls: 1904
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
cycles at 150 MHz:  853
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

1. Broaden the now-working profile-driven `SstMemoryBackend` path from the tiny
   normalized validation case to synthetic sweeps and real graph slices, and
   report simulator wall-clock throughput.
2. Extend the PMA contract for real edge weights before claiming weighted SSSP
   equivalence with Spine.
3. Add full PageRank and thresholded residual PageRank iteration controllers
   on the same PMA reader, gather, apply, and algorithm-policy interface.
4. Implement and synthesize the matching PMA-native HLS reader. Until then,
   normalized PMA-native cycles are simulator results, not measured hardware.
5. Add graph ingestion, batch manifests, dual update/algorithm oracles,
   GraSU-versus-Spine reports, SST-HBM sweeps, and PPA/energy accounting.

The first SST run and its stricter apply-pipeline boundary are recorded in
`docs/grasu_regraph_sst_normalized_20260725.md`.
