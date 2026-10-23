# Finite Prefetch And Compaction Diagnostic

## Decision

Simulator only. **Complete R performance retention has not passed.** The
latest [destructive Gather reuse control](GATHER_REUSE.md) passes all twelve
complete-convergence correctness/conservation executions and exactly replays
eight old controls. Candidate/A4 cycles are **0.953364 / 1.157245** at memory
latencies 64 / 128: only the first meets the declared +/-10% band. The
complete output scan already clears every row; removing repeated initialization
reduces complete cycles by 12.11% / 6.94% without changing physical traffic.
The preceding [wrapper write-issue control](WRAPPER_SCHEDULE.md) changes zero
complete cycles. The preceding
[Apply interval control](APPLY_SCHEDULE.md) changed complete time by less than
0.04%, including a small high-latency regression. Neither closes the gap.
The preceding [ring increase](PREFETCH_CAPACITY.md) also failed despite
128 KiB of added data storage. Both negative controls remain available.

All new architectures remain default-off. The latest candidate has sixteen
physical masters versus A4's thirteen and three state copies versus four;
this is not strict resource equivalence. No production replacement, hardware
timing calibration, publication reproduction or new Spine comparison is
admitted. No HLS or paper is changed. The [parent study](../README.md) owns
the unchanged production comparison; the records below preserve each control
and negative result without substituting an isolated reader floor for R time.

## Reading Guide

Ratios below are complete candidate/A4 cycles at latencies 64 / 128.
Every listed complete candidate fails the overall +/-10% retention gate.
Physical-memory service is unchanged across controls. The Apply and wrapper
records explicitly change response-anchored and pre-request component
intervals using schedule and RTL evidence; preceding architecture controls
leave timing unchanged. Gather reuse changes the initialization schedule,
not memory service or a timing coefficient.

The subsequent [current-input isolation](INPUT_ISOLATION.md) reuses that
latest finite reader without downstream computation. All sixteen executions
pass, with eight exact historical replays; fast-sink scans take 184,004 /
362,046 cycles. It exposes a high-latency credit/placement restriction without
changing the numerical core or admitting a new complete-R performance result.

| Record | Question or explicit resource change | Complete R ratio |
| --- | --- | ---: |
| [Complete convergence](CONVERGENCE.md) | Connect finite reader/compactor to the full R path | 2.591 / 2.197 |
| [Wait observations](OBSERVATIONS.md) | Read-only overlapping waits; exact replay, not a speedup | Unchanged |
| [Source loading](SOURCE_LOADING.md) | Independent finite source-cache loading | See complete record |
| [Reader ports](READER_PORTS.md) | Isolated two-master input diagnostic | Not complete R |
| [Isolated refill](BURST_REFILL.md) | Whole-parent reservation; high-latency regression retained | Not complete R |
| [Elastic pipeline](ELASTIC_PIPELINE.md) | Second reader master and third pipeline slot | 1.787 / 2.209 |
| [Metadata ports](METADATA_PORTS.md) | Third physical input master per frontend | 1.598 / 1.937 |
| [Apply ports](APPLY_PORTS.md) | Separate read/write masters on the same HBM bank | 1.555 / 1.554 |
| [Directory overlap](DIRECTORY_OVERLAP.md) | Second 8-KiB directory tile per frontend | 1.479 / 1.552 |
| [Ready bursts](READY_BURSTS.md) | Bounded addressed publication at eight-row boundaries | 1.0875 / 1.2474 |
| [Complete-path refill](READY_FULLBURST.md) | Same full-burst policy on the ready-burst topology | 1.08734 / 1.24729 |
| [Finite ring capacity](PREFETCH_CAPACITY.md) | 512 rather than 256 lines per parity; 128 KiB extra data | 1.08514 / 1.24316 |
| [Passive wait overlap](WAIT_OVERLAP.md) | First-round sampling on/off replay; no timing change | Not a new complete R result |
| [SSSP Apply schedule](APPLY_SCHEDULE.md) | Explicit post-response interval 100 -> 1, based on schedule/RTL | 1.084725 / 1.243611 |
| [SSSP wrapper schedule](WRAPPER_SCHEDULE.md) | Explicit pre-write interval 71 -> 2; all physical writes/responses retained | 1.084725 / 1.243611 (unchanged) |
| [Current-input isolation](INPUT_ISOLATION.md) | Same latest finite reader, fast and throttled sinks; unchanged numerical core | Not complete R |
| [Destructive Gather reuse](GATHER_REUSE.md) | Initialize each frontend once; retain every destructive output scan | 0.953364 / 1.157245 |

Each complete follow-up retains full state, active trajectory, physical traffic,
registration-order equality and exact old controls. Wait counters overlap and
are not additive stage times. An observed input endpoint includes downstream
backpressure, so it is not an intrinsic floor for another output schedule.

## Complete-Convergence Extension

The explicit `RoutedInputPath::kPrefetchCompactedExperimental` selection now
connects this reader and compactor to the existing Scatter, source service,
Gather, shared Apply, writeback and round barriers. The physical-slot path
remains the default. A private input owner holds the finite segment FIFO;
the reusable candidate is owned by `cpp/src/detail/prefetch_compact/`, not
duplicated in the diagnostic harness.

Compaction changes packet counts, not physical reads. Ingress and Scatter
therefore stop at TLAST with the physical packet count as a hard upper bound.
Ingress must not consume the next queued partition. Scatter must drain every
accepted packet before terminating. The complete round still waits for AXI,
state replicas, status and the existing downstream barriers. This experimental
selection currently admits positive weighted SSSP only; unsupported zero-weight
inputs and insufficient parent capacity are rejected explicitly.

`prefetch_convergence.py` declares twelve executions: strong original A4,
unchanged bank stream and compact-input R, at both memory latencies and both
registration orders. Eight legacy results must exactly replay the frozen
32-row matrix. The candidate must match all final state replicas and every
round's active count. Fresh core regression includes empty input, throttling,
source-cache window crossings, more than four destination partitions and
terminal-marker restart/rejection checks. No memory timing coefficient changes.

The complete integrated cases take 28,250,210 / 34,809,212 cycles, versus
A4's 10,904,254 / 15,840,606: **2.591 / 2.197 times** A4. All twelve rows pass
correctness, eight old rows replay exactly and fresh core/SST gates pass.
This is not a retention pass. The complete matrix and acceptance status are
tracked in the convergence record and its [evidence index](convergence.json). Raw
attempts remain separate; the older diagnostic below is unchanged and is
not a complete-R measurement.

The workload remains the frozen Amazon real-ID slice: 258,046 vertices,
1,450,899 weighted edges and four destination shards. The reference starts
from old converged SSSP state with three source-0 weight decreases and needs
46 synchronous rounds. This diagnostic reads its resident post-update PMA
once. Multiplying by 46 is a reader-only floor **if that same reader is used
unchanged each round**, not an executed complete-convergence candidate.

## Architecture And Checks

The [C++ ownership contract](../../../../../../../cpp/tests/evaluation_impact/prefetch_compact/README.md)
lists one responsibility per module. The Python CLI/analysis live in
`spine_cycle_sim/experiments/evaluation_impact/r_bank_stream/prefetch.py`
and `prefetch_analysis.py`, reusing the capped adapter diagnostic runner.

- Four physical 512-bit AXI masters, at most 16 parents each and 16 beats
  per parent. Metadata and both PMA parities share each frontend's master.
- Each frontend has 1024 directory rows and two 256-line PMA rings. Both
  pending and returned lines reserve storage; data comes only from AXI returns.
- An eight-bank selector skips at most eight empty rows/cycle and consumes
  at most one physical segment/cycle. Directory availability costs three
  cycles. Segment and packet pipelines each have depth two/latency two;
  they do not guarantee a sustained initiation interval of one.
- Stable live-lane packing uses 32 lane slots and eight-lane output. It
  preserves source-cache windows, partial-window padding and terminal markers.
  Segment/output FIFOs have 16/32 entries; blocked sinks propagate pressure.
- The current 71-cycle minimum issue-to-use delay, mock latencies 64/128,
  backend credits and registered arbitration remain unchanged.

Sixteen synthetic executions cover both latencies, forward/reverse component
registration, fast/throttled consumers and live/all-dummy input. They cross
directory tiles, source-cache windows, PMA bank halves and ring wrap. The
real-input matrix has both latencies and registration orders: all four pass
complete independent weighted-CSR edge comparison, TLAST, physical-slot and
dummy-lane conservation, request/beat closure and bounded storage. All source,
input, compiler and linked numerical-library pins remain unchanged during
each campaign. The numerical libraries are reused from checked passing core
gates; both new C++ executables are freshly compiled with GCC 15.2.0,
`-O3 -DNDEBUG -std=gnu++20 -Wall -Wextra -Wpedantic -Werror`.

## Results

| Observation | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| Unchanged adapter, one scan | 526,038 | 949,472 |
| Prefetch/compaction diagnostic, one scan | 424,166 | 432,565 |
| Candidate reader-only floor, 46 scans | 19,511,636 | 19,897,990 |
| Original A4-io16, complete 46-round computation | 10,904,254 | 15,840,606 |
| Candidate reader floor / complete A4 | 1.78936 | 1.25614 |
| Candidate parent requests per scan | 44,268 | 42,050 |

Every scan still reads **38,696,960 physical bytes** and emits every one of
the 1,450,899 live edges. Output packets fall from 951,224 to 181,464; reduced
dummy delivery is not reduced physical PMA traffic. The more concurrent,
bounded reader uses more/smaller parent requests than the old 3,803-request
path, and all are counted. Forward/reverse results agree exactly. Schema 2
adds observations only: projecting onto every old field exactly reproduces
all four schema-1 rows from the first candidate run.

The complete **unchanged production** R remains 32,178,380 / 57,588,504
cycles, or **2.951 / 3.635 times** strong A4. Candidate reader improvement
cannot be substituted for a new integrated R result.

## Remaining Issue Interval

A separate single-initiator probe requests 512 continuous beats with latency
three and 32 backend credits. Registered arbitration gives exactly 511
two-cycle issue gaps; the unregistered single-initiator control gives 511
one-cycle gaps. Both modes preserve all payloads and registration-order
results. This reproduces the current intent/grant handshake, not FPGA timing.

In the real candidate, worker 0 reads 211,765 beats and finishes at 424,166
cycles in the latency-64 case. The shared ledger records 604,640 accepted
beats, the same number of intents/grants/consumed grants, no multi-client
contention, and 606,247 failed submit attempts. At latency 128 there are
709,180 failed attempts and 104,540 capacity-blocked cycles. These counters
overlap and are **not additive exclusive stage times**.

The isolated probe supports investigating a pipelined reservation interface;
it does not justify simply disabling registration for G+R. Any change must
retain finite credits, fairness, order independence and request conservation,
and must be applied to/retested on **both A4 and candidate R**. A4's 13 masters
on nine banks versus the current R's seven masters remain a resource difference.

## Diagnostic Checkpoint Gates

The following list records the gates at the diagnostic-only checkpoint.
The extension above implements and passes the first three correctness and
compatibility gates, but the complete performance-retention gate still fails.

1. Define variable-packet end-marker handling through ingress, Scatter,
   Gather and round barriers. The production interface currently expects a
   fixed physical packet count; do not silently drop its padding packets.
2. Integrate an explicit candidate configuration and rerun full state,
   replica, active-trajectory and physical-traffic checks to convergence.
3. If production numerical code changes, freshly build/test core and SST in
   new directories and replay legacy evidence. The extension does so; the
   original diagnostic did not change production numerical code.
4. Retest A4 alongside any shared transport-model change. Keep both memory
   latencies and registration orders, then broaden input/resource controls.
5. Only then use an admitted baseline for the common warm-state Spine demo.

## Evidence And Reproduction

The portable [evidence index](evidence.json) records raw paths, hashes and
explicit non-admission flags. Raw outputs remain outside the repository:
`/data/chuxiao/experiments/r_bank_stream_comparison_20261022/prefetch-compact-v1/`
and `prefetch-compact-v2/`. Version 1 is the first numerical candidate;
version 2 only adds the transport probe/counters and exactly replays version 1.
No failed full-R candidate has been relabeled as a success.

The second complete service peaked at approximately 348.5 MiB, with zero
swap, under a 4-GiB hard/3-GiB high limit and group OOM kill. The live watchdog
sampled a 362,975,232-byte peak; it is not the authoritative cgroup lifetime
peak. Admission reserved 16 GiB total (own 4 + reserve 8 + background 4),
against 81,473,712,128 available bytes. No competing build reservation was
present and no foreign process or memory limit was changed.

From the repository root, choose a new service and output name:

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-prefetch-compact-NEW \
  -p MemoryMax=4G -p MemoryHigh=3G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=40min -p CPUAffinity=124 \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.prefetch \
  --output /data/chuxiao/experiments/r_bank_stream_comparison_20261022/prefetch-compact-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --core-gates /data/chuxiao/experiments/sharded_k4_bank_stream_profile_20261019/gates-v1 \
  --cpu 124 --admission-wait-seconds 600

python3 -m unittest tests.test_regraph_prefetch_compact \
  tests.test_regraph_adapter_floor tests.test_regraph_cached_core -q
```
