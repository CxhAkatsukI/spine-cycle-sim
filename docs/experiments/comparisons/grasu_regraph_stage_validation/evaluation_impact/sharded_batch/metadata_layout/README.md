# Runtime G Metadata Placement Diagnostic

## Decision

The complete 72-row diagnostic supports shared metadata-bank contention as
a cause of the chronological runtime slowdown. Replicating **both** immutable
tables brings every declared comparison within +/-10% of the independent
prepared-shard original; maximum absolute difference is **4.3618%**. Replicating
only row or binary metadata does not meet that complete-matrix test.

This is a resource-accounted simulator **control**, not a production change,
an original-paper reproduction, an HLS schedule check or FPGA calibration.
The original runtime still fails its 64K comparisons. All production, host,
hardware and publication admission flags remain false. No paper, frozen
figure, numerical core, default configuration or SST source was modified.

## Fixed Comparison

The [preceding chronological study](../chronological_inputs/README.md) supplies
the exact AU/SU/WK graphs and timestamp-ordered 4,096/65,536 insertion batches.
All retain its compaction, first-contact filtering, one-shard all-hot
reservation and complete-cache padding. These are explicitly transformed
temporal inputs, not the original GraSU converter or publication denominator.

The declaration is six inputs, two memory latencies (64/128 cycles), and six
arms. The first three replay the preceding original, four-bank candidate and
runtime-23 observations. The three new arms change only metadata placement:

| Arm | Row table | Binary table |
| --- | --- | --- |
| candidate-runtime-23 | Shared | Shared |
| runtime-row-copies | Four new copies | Shared |
| runtime-binary-copies | Shared | Four new copies |
| runtime-both-copies | Four new copies | Four new copies |

Search logic, finite queues, memory timing, credits, cache work and input
order are unchanged. Each updated shard pays its full 16-MiB cache preload
and 16-MiB acknowledged writeback. Timing starts with prepared resident
buffers and ends after final writes drain. Allocation, replica upload and
maintenance, reservation/reorder, DMA, host orchestration, seed preparation
and ReGraph are excluded on every arm. Replication therefore has a reported
storage cost, but **no measured host-inclusive cost** in this experiment.

## Complete Findings

Positive percentages mean slower than the prepared-shard original; negative
percentages mean faster. No row is selected or dropped based on speed.

| 64K batch | Latency | Shared runtime | Row copies | Binary copies | Both copies |
| --- | ---: | ---: | ---: | ---: | ---: |
| AU | 64 | +25.0172% | +22.7265% | +17.1955% | +0.5788% |
| AU | 128 | +23.1031% | +21.8489% | +14.8153% | -1.7218% |
| SU | 64 | +24.3472% | +21.9724% | +17.2898% | +1.3500% |
| SU | 128 | +22.6679% | +20.8527% | +15.0561% | -1.0111% |
| WK | 64 | +35.4614% | +33.2697% | +8.0749% | +4.3618% |
| WK | 128 | +34.0094% | +32.4892% | +4.3036% | +2.6435% |

All 4K comparisons pass even without copies; both-copy differences there
range from -0.5957% to -0.3100%. The
[complete matrix](evidence/matrix.json) retains every cycle value, not just
the larger batches. The [decision index](evidence/index.json) is independently
recomputed by delivery tests; all 36 preceding observations, traffic ledgers
and canonical full-state hashes replay exactly.

The separate [resident lifecycle check](lifecycle/README.md) extends coherence
coverage to three shards across three consecutive batches, with persistent
PMA, fixed reservation metadata and explicit initialization upload bytes.
All 12 executions pass; its capsule also replays every observation and state
hash in this 72-row study exactly after replica-allocation helper extraction.
That small, cache-dominated check is not larger multi-shard performance or
changed-reservation coherence admission. This earlier evidence is unchanged.

The subsequent [resident chronological check](resident_real/README.md) covers
4K/empty/61,440 insertions on two or three 8K shards. All 18 executions pass;
both-copy predictions differ by at most 0.7432% per nonempty batch. Shared
last batches still fail. It retains fixed future-union metadata, all-hot edits,
extra storage and excluded host time, so it is a bounded extension rather than
production/HLS/publication admission. Neither earlier capsule is overwritten.

Read-only progress observations support the placement explanation. For AU64K
at latency 64, the latest search completion moves from cycle 571,984 to
408,110 with both tables copied, while cache preload remains cycle 266,308.
Total cycles move from 838,309 to 674,436. Per-port requests and completed
beats conserve all physical traffic. Completion markers overlap and port
stall counts include retries; **neither can be summed into stage durations**.
This is not a new hardware stage calibration.

## Resource Cost And Limitations

Replica channels are fixed at `[3, 9, 15, 20]` within the existing 23 graph
channel IDs. The original metadata buffers remain, so each selected table
has five total copies, not four. Four new full buffers cost 8,699,904 to
9,027,584 bytes (8.30--8.61 MiB) for both tables. Used channels increase from
10 to 13; this is not an equal-storage or equal-active-bank comparison.

Every copy has a common 4-KiB-aligned base beyond all earlier allocations.
The address gaps are included in the per-channel span ledger; no copy may
exceed the 512-MiB per-bank capacity. Maximum summed spans are 62,017,536
bytes. The controls do not increase AXI masters or credits and do not make
metadata accesses free. Original buffers, replicas, PMA ownership copies,
untouched data and padding are all checked against full physical payloads.

Before choosing this for actual G, verify broader multi-shard performance,
changed-reservation coherence, real host replication costs, actual HLS buffer
binding and the finite search/cache clock and whole-G resource fit. The
resident extension checks fixed-reservation allocation/coherence and existing
legal connectivity only. Neither study establishes the remaining conditions.
Published source16/paper8 differences and temporal conversion also remain
open. Use this result to choose an implementation experiment, not to replace
Figure 7 or rescale Figures 8--11.

## Evidence And Reproduction

Raw root: `/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-metadata-layout-v1`.
`attempt-v2` is the complete matrix. The pre-diagnostic freeze is the preceding
raw study's `pre-metadata-6ea98f2.tar.gz`, SHA-256
`8ded1561aa0304dc61db6634bc6b162fdb807b232905741fa3af1f92b9233c86`.
Fresh source, compiler, library, configuration, binary and input pins are
recorded in the matrix; its raw archive embeds all input files and stdout
diagnostics. Large canonical states remain indexed outside Git.

Retained earlier attempts are separate from the 72 accepted observations:
`smoke-v1` failed compilation on a strict lifetime warning, fixed by copying
the region value; `smoke-v2` passed all six AU64K arms. `attempt-v1` was stopped
after seven accepted rows to correct a diagnostic validator: pending parents
include one staged input in addition to 32 active slots. The core budget and
timing were not changed. Logs and partial reports remain indexed in
[preflight evidence](preflight/index.json).

The successful bounded steps total 394.3 seconds; maximum recorded process
RSS is 391,660 KiB (0.374 GiB). Runs are serial, CPU-affined, with a 2-GiB
address-space limit, an 8-GiB available-memory reserve and 600-second timeout.
Minimum available memory at step admission was 22.26 GiB. Larger queued HLS
and R studies retain their stricter limits; none was bypassed or counted as
completed here.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.study run \
  --output /path/to/fresh-metadata-run \
  --prepared /path/to/chronological-inputs \
  --core-build /path/to/cached-handoff/banked/compatibility/build/cpp

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.study package \
  --matrix /path/to/fresh-metadata-run/results.json --output /path/to/fresh-evidence

python3 -m unittest tests.test_grasu_metadata_layout tests.test_grasu_metadata_layout_delivery -v
```

Review ownership: C++ `metadata_layout/layout.hpp` owns placement and complete
physical checks; `observed.hpp` owns read-only execution; `execution.cpp` is
the thin CLI. The corresponding Python package separates declaration,
analysis and execution/packaging. Production numerical code is unchanged;
the fresh strict Release harness, exact old replay and 66 focused Python/
organization tests pass. These are this checkpoint's checks, not a new full
core/SST regression claim.
