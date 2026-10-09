# Independent Original ReGraph Little Core

This is a separate component family, not another mode in the routed K4
baseline. Its current boundary is **Scatter's eight-update output through
Little Gather, local merge, and global merge**, stopping before Apply. Read
the [validation study](../../experiments/comparisons/grasu_regraph_stage_validation/LITTLE_FINITE_MODEL.md)
for accepted fixtures and limitations. It is not a complete original-ReGraph
cycle model or a published-throughput reproduction.

## Review Order

| Responsibility | Code |
| --- | --- |
| Fixed 64K partition, eight lanes, word formats, timing contract | [types.hpp](../../../cpp/include/spine_sim/original_regraph/types.hpp) |
| Registered bounded in-flight pipeline | [latency_pipe.hpp](../../../cpp/include/spine_sim/original_regraph/detail/latency_pipe.hpp) |
| Private URAMs, RAW forwarding, dummy filtering, full drain/clear | [little_gather.hpp](../../../cpp/include/spine_sim/original_regraph/little_gather.hpp), [little_gather.cpp](../../../cpp/src/original_regraph/little_gather.cpp) |
| Eight-lane local merge and independently arriving global inputs | [little_merge.hpp](../../../cpp/include/spine_sim/original_regraph/little_merge.hpp), [little_merge.cpp](../../../cpp/src/original_regraph/little_merge.cpp) |
| Finite-network fixture, invariant tests, exact author-source comparison | [tests/original_regraph](../../../cpp/tests/original_regraph/) |
| Admission, execution, negative controls, packaging | [original_regraph_validation](../../../spine_cycle_sim/experiments/original_regraph_validation/) |

## State And Flow

1. Each Little owns eight independent arrays of 32,768 64-bit rows. Each row
   holds two 32-bit vertex values: 2 MiB per Little, not one shared destination
   array for all pipelines. The initial modeled arrays are zero-filled.
2. A burst has eight updates, one per lane. Destination bit 19 suppresses
   dummy tuples; other destinations are masked to 16 local bits, as in the
   original source. PR considers all non-dummy updates active, even value zero.
3. Each lane keeps four recent row/value entries, oldest to newest. A matching
   recent row overrides the URAM read; the newest match wins. URAM writeback
   is delayed three cycles. This makes repeated even/odd updates to the same
   64-bit row an explicit RAW test rather than an instantaneous map update.
4. The Gather acceptance/completion pipeline must drain before partition
   output begins. It then reads and clears **every** private row, including
   zero rows. All eight lane FIFOs receive one row in order.
5. Local merge sums the eight lane pairs. Global merge holds one pair from
   each Little until all are available, sums them, and packs eight merged
   pairs into one 512-bit line. It retains partial arrivals and packing state
   during backpressure. Neither merger creates a sparse-output shortcut.
6. The global merger remains available across partitions; Gather can restart
   only at a drained boundary. Every drain clears its URAM arrays, and the
   forwarding history resets for the next partition.

The arrays and recent-value history are distinct modeled state. PR addition
uses explicit 32-bit words. Author-source comparison fixtures additionally
prove they stay inside the original signed-int arithmetic domain; arbitrary
signed-overflow equivalence is not admitted.

## Timing Assumptions

| Pipeline | Latency (cycles) | II | In-flight capacity |
| --- | ---: | ---: | ---: |
| Gather completion | 6 | 1 | 7 |
| URAM writeback | 3 | 1 | 4 |
| Full-row drain | 3 | 1 | 4 |
| Local merge | 3 | 1 | 4 |
| Global merge | 4 | 1 | 5 |

These are schedule-informed **simulation assumptions**, not a cycle-accurate
translation of HLS RTL. The source's `L=3` informs forwarding/writeback;
other depths follow the retained synthesis reports. Capacity `latency+1` is
an explicit conservative registered model choice, not a measured pipeline
register count. Clock is 210 MHz and ordinary lane FIFOs have depth eight;
tests also deliberately reduce depth and in-flight capacity.

The existing scheduler's prepare/evaluate/commit order is reused. A full
registered queue or pipeline cannot accept using space retired on that same
edge. Gather drain and local merge take their eight lane actions atomically;
global inputs arrive independently and may be held. A ready output blocked
by a full FIFO occupies its finite in-flight slot. Other available slots may
still accept work, modeling an elastic bounded pipeline rather than a verified
HLS global-stall-enable implementation. Exact internal HLS stall placement,
control/startup overhead, and external AXI stream depths remain unvalidated.

## Deliberate Omissions

This checkpoint supplies already scattered source-property updates. It has
no compact-edge memory reader, Scatter/source ping-pong protocol, memory
wrapper, DDR/HBM latency, outstanding requests, Big pipeline, mixed partition
scheduler, Apply, degree port, state writer, host orchestration, or PMA adapter.
The fixtures' feed/sink schedules are synthetic bounded controls, not hardware
traffic traces. Initial URAM zeroing is not charged as a hardware initialization
operation; the upstream functional control uses `SW_EMU` zero initialization.

Consequently the reported cycles cannot be converted into whole-R MTEPS,
compared with Table IV, or attributed to adapter overhead. Those comparisons
require completing and admitting the missing interfaces on this same downstream.

The separate CMake library is dependency-free except for existing simulator
primitives. It is intentionally absent from the SST plugin source list until
there is a complete, validated original-R wiring. Existing Spine/G+R components
and frozen SST binaries are unchanged.
