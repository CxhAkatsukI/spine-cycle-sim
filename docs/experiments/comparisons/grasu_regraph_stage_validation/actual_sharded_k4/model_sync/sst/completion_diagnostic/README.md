# Completion And Shared-Port Diagnostic

## Finding

**A cross-operation stall is reproduced in the current AXI model. It has
not been fixed, and this is not a hardware timing acceptance.** The parent
[six-row SST checkpoint](../README.md) and its frozen archive remain intact.

This follow-up explains why some model `lksg` completion events occur after
the adapter's empty-row tail, unlike the hardware timeline. It does not
explain the entire overall timing discrepancy, and it does not change any
model schedule, latency, capacity or production HLS.

## Whole-System Observation

The exact final plugin and WK-original resident fixture from the parent
campaign were replayed with a deliberate stop at 20,000,000 cycles. It
took 22.82 seconds and about 611 MiB maximum process RSS, with an 8 GiB
limit and 16 GiB reserve. This truncated observation is **not** a completed
workload correctness run; `success=false` and `done=false` are expected.

At the stop:

- Workers 1--3 have completed ingress and Scatter, but their Gather outputs
  are backpressured. Each Gather output FIFO is full at 16 rows.
- Worker 0 has emitted all 32,768 Gather rows for its first shard and has
  started its next `lksg`, before its first adapter has finished its empty
  row scan. Its next invocation is waiting for input.
- Worker 0's source responses are full at 16 external and 8 internal lines;
  the physical read-beat FIFO is full at 32. Source prefetch is blocked
  while waiting for the next adapter stream.
- The ordered shared path is backed up: its three global queues are all
  full at 16. Source-master 0 retains 16 parents and 16 bursts, and its
  shared-port router retains 17 routes. Backend outstanding is zero at
  this instant, which does not mean every response has been consumed.

These are directly saved model states, not an inference from total runtime.
They identify a waiting chain involving next-shard source prefetch, the
source/writeback shared port and the global output path. A state snapshot
alone cannot attribute every stalled cycle to one cause.

## Isolated Control

`cpp/tools/routed_regraph/diagnose_stream_write.cpp` uses one unchanged
`FixedAxiPort` and the tested core library. It submits a 512-byte read,
then a separate 64-byte write at cycle 50. The streamed-read FIFO has one
entry and the reorder buffer has two. All controls check full read/write
payloads, two parent completions, nine backend beats, complete drain, and
identical observations under reversed component registration.

| Control | Read consumer | Write issued | Write acknowledged | End |
| --- | --- | ---: | ---: | ---: |
| Streamed read, held | Starts consuming at cycle 200 | 211 | 216 | 217 |
| Streamed read, drained | Consumes throughout | 53 | 58 | 59 |
| Ordinary read | No streamed consumer required | 53 | 58 | 59 |

The delayed write is therefore reproducible without graph algorithms,
PMA layout, sharding, DRAMSim3 or host relaunch. This isolates a model
cross-operation interaction; it is not a board measurement.

Code inspection identifies two relevant constraints in `cpp/src/axi.cpp`:
`evaluate_data_channel` selects only streamed-read bursts while any such
burst remains active; if those reads have all been issued but have not
retired, the selection can stop without issuing a ready write.
`evaluate_backend_responses` also consumes a prefix of a shared response
queue and stops at a streamed read when its reorder capacity is full.
The isolated test demonstrates the combined stall. It does not separately
quantify these two mechanisms or prove the exact board AXI implementation.

## Implications And Next Gate

The earlier zero tail medians on SU/WK were not evidence of zero metadata
cost. Some `lksg` invocations were delayed by downstream model waiting.
The parent package's `gather` labels denote whole `lksg` invocations,
not exclusive Gather-phase counters.

Correcting inappropriate read/write coupling may make the model **faster**.
Since the existing model already underpredicts board compute spans, this
correction cannot by itself solve the nominal timing discrepancy. Memory
latency/address mapping and measured kernel scheduling still need checking.
Do not choose a coupling rule or latency multiplier merely to match totals.

The next implementation needs an explicit, separately validated treatment
of read/write issue and response backpressure for the measured shared
master. Read ordering, finite read/write credits, physical bandwidth,
response buffering and payload conservation must remain enforced. It
must pass stalled-read/write-progress controls, the complete candidate
matrix and unchanged legacy gates before timing can be reconsidered.
The previously measured old/new FPGA speedups are not changed by this
model-only finding.

## Evidence And Reproduction

[completion.json](completion.json) contains the capped state, isolated
controls and resource records. [completion_raw_index.json](completion_raw_index.json)
hashes every member of [raw_completion.tar.gz](raw_completion.tar.gz).
The archive includes capped outputs, queue diagnostics, the tested core
library, diagnostic executable/source, build commands and retained initial
attempts. The large resident input and final plugin are referenced by hash
in the parent archive rather than duplicated.

Rebuild the isolated diagnostic against the parent tested library:

```bash
g++ -std=c++20 -O2 -Wall -Wextra -Werror -Icpp/include \
  cpp/tools/routed_regraph/diagnose_stream_write.cpp \
  /data/chuxiao/experiments/sharded_k4_sst_sync_20261011/core/cpp/libspine_cycle_core.a \
  -o /absolute/fresh/diagnose_stream_write
/absolute/fresh/diagnose_stream_write
```

The archived capped `run_config.json` and resource command replay the
whole-system observation after explicitly relocating paths. Keep its
20-million-cycle cap and expect an unfinished result, not a pass.
`completion_delivery.py` in the owning study package revalidates and freezes
these observations into a fresh output directory; it refuses overwrite.
