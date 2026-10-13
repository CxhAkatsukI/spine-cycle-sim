# Full Cached Sharded Handoff

## Question And Boundary

Does the finite-search, complete-cache G candidate correctly update sharded
physical PMA, including high source IDs and cold segments, before handing the
same bytes to R? This is a **correctness and integration checkpoint**, not a
performance-retention, original-publication or FPGA admission decision.
The preceding [bank-routing checkpoint](../banked/README.md) used direct
processors and small cache geometry. Its passing result did not establish the
complete cached candidate's behavior in sharded memory.

G pays the full hot-window preload, finite search/edit pipeline, cold edits
and acknowledged hot-window writeback. R then consumes the resident PMA and
propagates from old-graph converged SSSP distances to new-graph convergence.
Allocation, state upload and caller-prepared seeds remain outside these
device windows. No host-orchestration or device-seed timing is claimed.

## Declared Matrix

Four fixtures each have an unchanged direct-G control and two complete-cache
G runs with opposite **R** registration orders: twelve executions total.

| Vertices / shards | High source | Location of high-source updates | Batch |
| --- | --- | --- | --- |
| 65569 / 2 | 65536 | Hot cache | Four weight decreases, eight physical operations |
| 65569 / 2 | 65536 | DDR | Same operation count; four hot and four cold operations |
| 131105 / 3 | 131072 | DDR | Same operations; third shard remains untouched |
| 65569 / 2 | 65536 | DDR allocation retained | Empty; all shards untouched |

Each shard retains two complete 131072-segment hot halves and padding attached
to an empty source row. Cold fixtures put high-source rows after that padding.
The reserved-but-unused insertion and every padding segment stay allocated
and visible to R. These graphs have few live edges and deliberately large
physical padding: they are not representative performance workloads.

Both nonempty updated shards preload and write back 16 MiB each. Therefore
cached G must read **32 MiB** and write **32 MiB**, plus 256 B in each direction
for the mixed hot/DDR fixtures. Direct G transfers 512 B per direction.
Empty G launches no updated shard and transfers no PMA bytes. No cache load,
writeback, cold edit or untouched extent may be silently omitted.

## Invariants And Timing Assumptions

- Every final physical segment, including padding and untouched shards,
  equals a separate functional edit oracle. The logical graph also matches.
- R uses the same addresses and payloads, without a rebuild, repair or hidden
  memory traffic. Independent Dijkstra checks all final distances.
- R cycles, rounds, read/write bytes and final source replicas equal the
  direct-G control. Reversing R registration must preserve all observations.
- G/R windows do not overlap; all AXI requests, responses and final writes
  drain before the next window. Byte ledgers must close.
- Memory assumptions are unchanged: 150 MHz; Mock latency 7; 32 channels;
  one issue/channel/cycle; 16 outstanding/channel; response depth 32. The
  actual runtime allocator uses the existing 23 graph banks. Updated shards
  are launched sequentially; this is not concurrent four-shard G.
- Finite search retains 64 contexts and one shared 32-credit metadata master
  per CU. The cache retains its explicit finite banks and update pipeline.
  These are model assumptions pending the separately queued HLS checks.

The test initially hit the inherited one-million-cycle G limit while full
cache writes remained outstanding. Only complete-cache fixtures receive a
four-million-cycle execution limit; direct tests retain one million. This
changes the watchdog, not simulated latency, bandwidth, work or measured
cycles. R retains twenty million cycles. Earlier failed preflight logs remain
part of the delivery; reaching an execution limit is not discarded evidence.

## Execution And Delivery

**All twelve executions passed.** The frozen [index](evidence/index.json),
[report](evidence/report.json) and [raw capsule](evidence/raw.tar.gz) include
the observations, source/build identities, compatibility evidence and all
four preflight attempts. The capsule includes the earlier G regression as a
nested package rather than duplicating its large JSON trees in Git.

Forward and reverse R registration orders give identical observations:

| Vertices / shards | High-source path | Cached G cycles | R cycles / rounds | G PMA bytes, each direction |
| --- | --- | --- | --- | --- |
| 65569 / 2 | Hot | 1048650 | 11763210 / 5 | 33554432 |
| 65569 / 2 | DDR | 1048650 | 11923060 / 5 | 33554688 |
| 131105 / 3 | DDR; third shard untouched | 1048650 | 17452660 / 5 | 33554688 |
| 65569 / 2 | Empty batch | 0 | 2384612 / 1 | 0 |

Direct G takes 182, 182, 188 and zero cycles respectively and produces exactly
the same R observations. This deliberately sparse, padded fixture makes full
cache traffic dominate; the direct/cached timing ratio is **not a realistic
workload performance comparison**. The empty case checks quiescence, not
update throughput. Identical cached G cycles across the three nonempty cases
are observed, not forced: all pay two complete sequential cache windows, and
the few cold edits finish before the writeback tail.

Fresh Release verification passes **34/34 CTest targets** and exact replay of
all **228** preceding G observations. Previous direct and banked handoff
stdout, default routed stdout, and both default SST result JSON objects are
unchanged. The SST check establishes default compatibility only, not finite
candidate timing calibration. All 121 focused Python tests pass, including
portable capsule hash, raw-observation and nested regression checks.

The final twelve-row run takes 215.82 seconds wall time with 771304 KiB peak
process RSS. The largest measured verification process is the SST build at
1019848 KiB; every recorded core/SST/handoff step is bounded to 2 GiB with an
8-GiB available-memory reserve. RSS is `wait4` maximum process RSS, not a
simultaneous process-tree sum. Builds and tests are serial. No performance,
hardware or complete-baseline admission follows from these passing checks.

Python ownership remains in `composition/`: `cached_analysis.py` validates
observations, `cached_study.py` runs bounded checks, and `cached_delivery.py`
packages them. C++ fixture and execution helpers remain in
`cpp/tests/evaluation_impact/handoff/`; no production component is modified.

Use fresh output paths:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.composition.cached_study \
  --output /path/to/new-attempt \
  --pre-edit /path/to/frozen-pre-edit \
  --previous-routed /path/to/frozen-default-routed.stdout.txt \
  --previous-matrix /path/to/finite-model/matrix-v1/results.json \
  --previous-sst /path/to/preceding-handoff/compatibility

python3 -m spine_cycle_sim.experiments.evaluation_impact.composition.cached_delivery \
  --report /path/to/new-attempt/results.json \
  --output /path/to/new-evidence \
  --pre-edit /path/to/frozen-pre-edit \
  --previous-matrix /path/to/finite-model/matrix-v1/results.json \
  --previous-sst /path/to/preceding-handoff/compatibility

python3 -m unittest tests.test_grasu_cached_handoff -v
```

Builds and tests are serial with a 2-GiB process address-space limit and an
8-GiB available-memory reserve; matrix children use 1 GiB. Larger queued jobs
retain their existing higher reserves. Raw machine-local root:
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-cached-sharded-v1/`.

## Remaining Gates

Sharded performance on realistic batches, full-G HLS/FPGA timing, original-G
publication matching, R resources/credit controls, host and seed accounting,
and a new matched Spine comparison remain separate. Passing these fixtures
does not replace Figures 7--11 or close the overall baseline goal.
