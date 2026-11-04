# Weighted SSSP FPGA Stage Admission

The returned sharded K4 image passed the independent update (G) screen and
both Amazon weighted gather/apply (R) screens. It missed the 15% R gate on
the AskUbuntu topology control. Each row contains one measured run per arm,
without averaging.

| Stage and input | Public-source control (ms) | Integrated image (ms) | Integrated/control |
| --- | ---: | ---: | ---: |
| G: AskUbuntu, 131,072 updates | 18.413633 | 7.064731 | 0.38367 |
| R: Amazon, sparse weighted frontier | 10.404206 | 9.843290 | 0.94609 |
| R: Amazon, alternate weighted frontier | 10.591011 | 10.054087 | 0.94930 |
| R: AskUbuntu reciprocal slice, one active source | 2.189131 | 2.617133 | 1.19551 (fails) |

Both arms of each row used the same U55C and driver-reported clocks
`[150, 500, 450, 0]` MHz. G used `0000:c1:00.1`; all R rows used
`0000:82:00.1`. Time runs from the first participating CU start through the
last CU completion, including internal gaps. Setup/staging before that span
and final oracle readback are excluded. G's native oracle checked 716,992
packed words with zero mismatches. The independent public-source GraSU
control also checked its full PMA state.

The R reference is the public-source four-Little A4 implementation with the
weighted active-min algorithm and matching publication semantics. It is not
an unmodified ReGraph paper run or proof of identical physical resources.
The two Amazon rows use the same graph (735,324 vertices, 5,158,388 logical
edges) with different matched weighted state and edge inputs. They produced
10 and 315,863 active outputs, respectively. They are separate workload
controls, not repeats or independent graph topologies. The R gate measures
one nonempty resident superstep, not convergence. Every candidate replica
and apply output matched the reference oracle after omitting the A4 guard
line (16 extra words); both reference and candidate retain their full
separate output dumps.

The integrated bitstream SHA-256 used for all four rows is
`1bb1532fd7b1bcb182ed9093e6640f6ab0fa6ae27707dcc509a7cc3881b61c25`.
The public R control SHA-256 is
`5185d9be6f0b889f8da107fb3a6d9b5d3d62d4affe4cfc6a1910833ddcfda3b4`.

## AskUbuntu Topology Control

Both arms use the same fixed-ID reciprocal slice, 156,289 vertices and
903,774 logical edges, and the same deterministic positive weights and
one-source initial state. The fixed-ID compact layout has twelve A4 tasks
over three destination partitions. The independent oracle reports 5,264
improved vertices, and both FPGA outputs pass. This is an R-only
superstep on a real-topology slice with synthetic weights, not the
full AU resident update and convergence workload.

The integrated span is 428.002 us longer and needs a reduction of at least
99.633 us to meet the gate at this reference time. The last of the three
adapter events ends about 0.807 ms before the last participating CU
completes. The three serialized mux events are separated by less than
1 us each. The timings rule out a large gap between host mux submissions
as the explanation; they do not separate input wait, gather tail and
publication service within overlapping CU events. The candidate schedules
one frontend per destination partition, leaving the fourth idle in this
case; the A4 control subdivides each partition into four tasks.

The [raw AskUbuntu archive](sssp-au903k-r-pair.tar.gz) preserves the
failed performance receipt, correctness outputs, kernel event logs,
clock records, and offline layout and fixture manifests. The checked-in
source topology is `tests/data/askubuntu_reciprocal_full/askubuntu_reciprocal_full_e903774.slice`.
The `hardware.board_execution.active_min_capture` module in the
original ReGraph experiment generates the fixed-ID weighted input using
the A4 probe built from
`cpp/tests/evaluation_impact/warm_comparison/fixed_id_layout.cpp`.

### Host Launch Order Control

The [frontend-first host variant](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/70d3b01)
submits the leading adapter and gather before the shared HBM and apply CUs.
It uses the same routed image and same first-start to last-completion
boundary, which now starts at the adapter. The frozen A4 receipt is replayed
by hash, input identity, raw clock evidence and full output oracle. Only
the changed candidate ran on the board.

The variant measured **2.610194 ms**, a 6.939 us difference from the first
candidate and still **19.23% slower** than A4. Both executions passed the
same exact-output check. This launch-order change does not resolve the
performance gate; it is not selected for the convergence campaign. The
[raw follow-up archive](sssp-au903k-r-frontend-first.tar.gz) includes the
changed-host digest, event logs, outputs and the reference replay receipt.

### Source-Property Read Burst Repair

The previous weighted wrapper's synthesized `emit_source_block` issued
single-beat AXI read requests on both source-property ports. The
[wrapper repair](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/9ceb5c5)
selects the input pointer and output FIFO before the pipelined block loop.
In the rebuilt XO the two read ports request 256 logical beats per block;
the generated AXI adapter caps physical bursts at 16 beats and retains
16 outstanding reads. This is a synthesis observation, not a board timing
result or a claim that the source reads explain the entire AskUbuntu gap.

Only the source-property wrapper XO changes from the directory-span
SSSP link inputs; the adapter, gather, apply, GraSU, connectivity and clocks
are unchanged. The replacement XO SHA-256 is
`e6955520e720eef0d2f14a49440177fa9cc77783e8d9cedc7674193ef9934cbf`.
The [remote build record](REMOTE_LINKS.md#weighted-sssp-source-read-burst-retry)
identifies the link and its board-test dependencies.

The three R retests reuse their respective public A4 receipts after replay
of input, clock and correctness evidence. Only the changed candidate is
measured, once per fixture. A separate G run checks the exact same returned
image. The first resident comparison (full AskUbuntu) cannot start unless
all three R fixtures and G pass.

### Nominal Source-Burst Board Screen

The physical-optimization link produced image SHA-256
`32b73f1772ffbaf0e1ee4ab7c63626e1c5a50e0515f78db38462f29bf5a89886`.
The candidate and the frozen public weighted A4 references used the same
U55C (`0000:82:00.1`) with driver clocks 150/500/450/0 MHz. Each row
uses one correctness-checked observation per arm, with the earlier
reference reused. The boundary is the device event span from first
command start to last completion for one round on resident inputs.

| R fixture | Public A4 (ns) | Adapter + R (ns) | Elapsed change | 15% gate |
| --- | ---: | ---: | ---: | --- |
| AskUbuntu 903,774 edges | 2,189,131 | 2,658,355 | +21.43% | Fail |
| Amazon | 10,404,206 | 9,827,686 | -5.54% | Pass |
| Amazon, higher activity | 10,591,011 | 9,936,380 | -6.18% | Pass |

The same image independently passed G on AU 131K: **7.298286 ms**
versus **18.368928 ms** for the public control. All 716,992 checked PMA
words matched. The failed AU R screen prevented the resident AU and
eight-graph SSSP comparisons from starting with this image.

The AU run needs about **141 us** less elapsed time to pass. The final
adapter completed **811 us** before the last device event. The two gaps
between ordered mux commands were **0.610 us** and **0.440 us**;
the second and third mux commands themselves lasted **264 us** and
**271 us**. These are overlapping command spans that include waiting
and backpressure, not exclusive mux, gather, or apply times. The gaps
alone cannot explain the miss. Each integrated destination shard is
assigned to one frontend; A4 splits each of the three destination
ranges across four Little lanes. The existing screen measures the
combined difference and does not isolate the effect of that schedule.

[Raw evidence](sssp-source-bursts-nominal-board.tar.gz) contains the
three paired R receipts and FPGA event logs, the G receipts, the
[AU/512 setup result](FIGURE_IMPACT.md#repaired-g-same-card-au512-check),
and the rejected resident queue records. Archive SHA-256:
`4fd2f515c34cb5e2017790dfe578c1991d871714178848cb01e6f55cdbe5ea81`.

### Matched 445-MHz HBM Diagnostic

The first source-burst image returned at a lower HBM clock than requested.
The public A4 reference and both integrated observations below were timed
on the same U55C (BDF `0000:82:00.1`) with identical driver-reported
150/500/445/0-MHz clocks. All used the same resident AU 903,774-edge weighted
SSSP superstep. Timing is from the first participating CU start to the last
CU completion; it excludes G, host preparation and convergence after the
superstep. The A4 arm ran once; the second integrated host reuses that
frozen receipt. Both candidate runs returned the same logical state as A4
and matched the independent oracle on all reported replicas.

| Arm | Elapsed (ms) | Overhead vs A4 | R gate |
| --- | ---: | ---: | --- |
| Public A4 | 2.147288 | reference | - |
| Source-read bursts | 2.510750 | 16.93% | Fail |
| Same image, first-wave host arguments prebound | 2.610934 | 21.59% | Fail |

The 15% threshold is 2.469381 ms. Prebinding moved the last adapter start
about 8 us closer to the first CU start but did not shorten the measured
device span. The new host recorded 2.720117 ms from argument binding to
queue completion, with no equivalent old host wall timer. This diagnostic
[host change](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/67ce64d)
is not promoted. These one-shot observations do not attribute the remaining
gap to a specific CU, admit the image at nominal clocks, or substitute for
independent G validation.

The [raw diagnostic archive](sssp-au903k-burst-hbm445-screen.tar.gz) retains
the frozen A4 receipt, candidate receipts, event logs, clock records and
oracle/output bytes. The external fixture, host executables and xclbins
are pinned by the receipts rather than duplicated. The candidate receipt
SHA-256 values are
`eaf43e0e826240f9833f48a5e72758384835d5f2be84773a1e8928ad67b7a2e3`
and `68d08f1846780361504b0fb5de17bd50e89f0743810edd2fbf5b6fe3d0e5aac9`,
in table order.

### Where the 445-MHz Difference Appears

The frozen CSR has no empty source rows, so the candidate's no-update
reordering preserves the A4 vertex IDs. Replaying the candidate PMA
allocation reproduces all 3,787,088 slots in the native host receipt. The
destination ranges below therefore contain the same logical edges in both
arms. Times are relative to each arm's first device event.

| Destination range (shard) | Logical edges | Candidate PMA slots | Candidate mux window (ms) | Last A4 Little end (ms) |
| --- | ---: | ---: | ---: | ---: |
| 0 | 590,974 | 2,279,184 | 0.173 to 1.967 | 1.124 |
| 1 | 272,970 | 1,304,480 | 1.968 to 2.224 | 1.778 |
| 2 | 39,830 | 203,424 | 2.224 to 2.481 | 2.119 |

Shard 0 contains 65.4% of the edges and 60.2% of the slots, and occupies
71.4% of the entire candidate device span in its mux window alone. The
three mux windows have only 1.340 us of gaps between them. A4 runs four
Little tasks per destination range; the candidate starts one adapter and
gather per range, leaves the fourth frontend unused, and drains the
ranges in order. The first adapter finishes at 1.774 ms, about 193 us
before the first mux finishes. The second and third adapters finish
before their mux windows begin.

This identifies the first shard as the largest exposed window and rules
out gaps between mux submissions as the main cause. The mux and Little
endpoints are not the same operation. A CU window can include stalls
from other CUs; the numbers do not isolate PMA/HBM waits, gather work,
or shared publication backpressure. In particular, dividing 3,787,088
PMA slots by A4's 904,184 physical edge records is not a traffic ratio:
the layouts have different record sizes and side traffic.

If the nominal source-burst retry still misses, a follow-up should
instrument progress on both sides of the first gather: adapter output
accepted versus stalled, gather output accepted versus stalled, and
mux input empty versus downstream blocked. An idle fourth frontend does
not by itself justify splitting a destination range. Such a design
would also need to merge partial updates before apply and preserve the
PMA update mapping. This diagnosis does not admit a new image or
estimate a speedup from repartitioning.

To reproduce the layout from the existing fixture, without running
either arm again, run from the simulator root:

```bash
python3 -c '
from pathlib import Path
import sys
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.shard_layout import replay_layout
print(replay_layout(Path(sys.argv[1]), dict(
    vertices=156289, shards=3, edges=903774, pma_slots=3787088)))
' /data/chuxiao/checks/source-retention-repair-20261104/a4-active-au903k-v1/fixture/inputs
```

The raw candidate `candidate.stdout.txt` and A4 `reference/result.json`
in the diagnostic archive contain the event times. The A4 descriptor
in the same pinned fixture assigns four Little events to each range
in ordinal order.

## Evidence

[Raw evidence archive](sssp-stage-admission.tar.gz) preserves both R queue
and pair receipts, FPGA event logs, device and clock records, exact output
buffers and host provenance, plus both G receipts and logs. Absolute
paths in the captured reports refer to the run host; the archive
directories retain their original basenames. The reports pin the
external graph/fixture, hosts and bitstreams by SHA-256 rather than
duplicating them here. The production audit code is in
`spine_cycle_sim/experiments/original_regraph_execution/hardware/board_execution/`.

For a simple byte-level R replay after extracting the archive, run this in
each R evidence directory:

```sh
cmp pair/offline/expected.u32le pair/reference/expected.u32le
for output in pair/candidate/*.u32le; do
    cmp -n "$(wc -c < "$output")" pair/offline/expected.u32le "$output"
done
```

The paired weighted-SSSP convergence measurements on this image remain
valid as version-pinned observations. The new topology control prevents
claiming representative cross-topology R retention for that image.
It neither validates CC or ResPR nor supersedes the existing figure data.
