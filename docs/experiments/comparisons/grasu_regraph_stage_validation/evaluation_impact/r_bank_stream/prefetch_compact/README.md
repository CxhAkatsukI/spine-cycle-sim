# Finite Prefetch And Compaction Diagnostic

## Decision

Simulator only. Correctness, conservation and finite-storage checks pass;
**complete R performance retention has not passed**. The reader/compactor was
first tested with stall-free sinks; a default-off complete-R extension now
passes all twelve correctness/conservation executions but fails retention.
Neither is a replacement production profile, FPGA timing
measurement or new Spine comparison. No HLS or paper is changed. Start with
the [parent study](../README.md) for the unchanged R matrix and the
[complete-convergence record](CONVERGENCE.md) for the new extension. The
[passive wait observations](OBSERVATIONS.md) exactly replay all twelve
convergence results; they diagnose overlapping waits, not a further speedup.
The subsequent default-off [source-loading experiment](SOURCE_LOADING.md)
tests independent finite cache writes without changing old controls; its
complete performance gate is not yet admitted.
The [explicit reader-port diagnostic](READER_PORTS.md) separately tests two
physical masters per frontend with unchanged PMA traffic. It does not change
the integrated default or substitute a reader floor for complete-R timing.
The [full-burst refill experiment](BURST_REFILL.md) tests whether reserving
whole parents reduces short-request fragmentation with the same rings and
physical reads. Its preregistered gates remain separate from R admission.
The [explicit elastic-pipeline candidate](ELASTIC_PIPELINE.md) adds a third
finite pipeline slot and a second physical reader master. All twelve complete
executions pass correctness and eight old controls replay exactly. Retention
still fails: 1.787 / 2.209 times A4 cycles. The candidate improves latency 64
by 29.05% but regresses latency 128 by 2.73%; it remains default-off.

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
