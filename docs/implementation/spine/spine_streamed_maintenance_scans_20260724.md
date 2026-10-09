# Spine streamed maintenance scans

Date: 2026-07-24

## Scope

This milestone replaces the maintenance model's former "read the complete
sorted array, then scan it" behavior with request-scoped AXI read beats and a
bounded producer/consumer pipeline. It also adds the hot/cold input-count pass
present in the current `reduce-levels-for-routing` HLS source.

The source-following revision is
`afb8199a2ca8d3fd208b985324bf4d8719e2b839`. Timing parameters come from the
accepted split-kernel synthesis bundle at revision
`9c08763148644df262c0d374e782bc834f4c0f4f`:

| HLS loop | Achieved II | Loop latency |
| --- | ---: | ---: |
| hot/cold input count | 1 | `N + 19` |
| per-family L0 coalesced count | 1 | `N + 19` |
| per-family L0 write | 24 | `24 * (N - 1) + 43` |

The report paths are:

- `partitioned_run_maintenance_Pipeline_PARTITIONED_MAINT_COUNT_HOT_COLD_INPUT_csynth.rpt`
- `partitioned_count_l0_coalesced_rows_family_Pipeline_PARTITIONED_COUNT_L0_COALESC_csynth.rpt`
- `partitioned_write_l0_family_Pipeline_PARTITIONED_WRITE_L0_EDGES_csynth.rpt`

under `/data/feiyang/spine-dynamic-graph/tests/test_integration/
csynth_readmaint_prj/sol/syn/report/`.

## Execution model

`AxiRequest::stream_read_beats` opts one read request into a finite beat stream.
The AXI master still builds the complete parent response for compatibility, but
also publishes each returning beat with transaction ID, address, parent offset,
payload, and `last`. Returning data first enters a bounded 32-beat AXI response
reorder structure and is then published into a bounded 32-beat FIFO. The
maintenance consumer has a separate configurable, 32-edge default reorder
capacity. Filling any downstream structure eventually stops backend response
retirement, so backpressure reaches SST/DRAMSim3.

Streamed bursts belonging to one parent request are issued in increasing parent
offset order. This avoids a head-of-line deadlock in which an arbitrary burst
schedule could fill the finite reorder structure before the next edge needed by
the in-order maintenance loop had even been issued. Non-streamed AXI traffic
retains the generic round-robin burst policy.

Only maintenance sorted-edge scans opt in. This is important because HBM16 is
also used as reader task scratch and persistent dirty storage. Those requests
continue to use ordinary parent responses and cannot leave unconsumed beat
events on the shared port.

The maintenance consumer:

1. issues one logical sorted-array read per HLS scan pass;
2. receives 16-byte sorted-edge beats through a 32-entry FIFO;
3. reorders up to the configured capacity by parent offset and retires only the
   next expected edge;
4. starts loop work when the first edge arrives, while later beats remain in
   flight;
5. enforces the selected loop II and the report-derived pipeline tail;
6. holds the parent transaction until every streamed beat has been consumed.

The source-shaped cold L0 path now executes:

- one dirty-validation pass;
- one dirty-mark source pass;
- one hot/cold input-count pass;
- sixteen per-family precount passes;
- one L0-write pass for the active family.

For the ten-edge Amazon fixture this is 20 passes and 200 edge visits, not the
former 19 passes and 190 visits.

## SST evidence

All rows use the same file-backed graph, HLS-shaped AXI profile, 32-channel SST
HBM/DRAMSim3 backend, and correctness oracle.

| Case | Cycles | Backend requests | Correctness | Notes |
| --- | ---: | ---: | ---: | --- |
| Amazon, achieved L0 II=24 | 6,962 | 1,378 | 0 mismatches | 200 streamed beats |
| Amazon, L0 II=1 what-if | 6,753 | 1,378 | 0 mismatches | same work and memory bytes |
| Carry + hot/cold | 8,402 | 1,895 | 0 mismatches | 36 passes, 72 beats |
| Amazon, response capacity=2 | 6,962 | 1,378 | 0 mismatches | 161 reorder-full stalls |

The Amazon baseline records 203 response-wait cycles, 207 II-stall cycles, 365
pipeline-tail cycles, and a maximum nine buffered sorted edges. Changing only
L0-write II from 24 to 1 gives a 1.031x end-to-end speedup. This is a structural
execution-driven what-if, not a new synthesized hardware result.

Reducing only the maintenance response capacity from 32 to 2 bounds observed
occupancy at two and introduces 161 reorder-full stalls, but does not change the
6,962-cycle total for this tiny case. The blocked ingress is hidden by memory
arrival and loop-II timing, so a stall count is diagnostic evidence, not by
itself evidence of an end-to-end bottleneck.

Relative to the preceding source-shaped AXI milestone (`6517 cycles`, `1368`
requests), the corrected default is 445 cycles slower and adds exactly ten
backend reads for the previously omitted hot/cold pass.

## Validation

The C++ suite includes a generic two-entry beat-FIFO test. It proves finite
backpressure, ordered offsets, `last` framing, exact payload, parent-response
closure, and request-scoped opt-in on a shared AXI port. Spine tests close the
following identity for source-shaped scans:

```text
edge_visits = dirty_validate + dirty_mark + hot_cold_count
            + family_precount + l0_write
streamed_beats = edge_visits
streamed_payload_bytes = sorted_read_bytes
```

The 256-edge C++ pressure test reaches the 32-edge maintenance capacity and
records 5,099 maintenance reorder-full stalls plus 4,333 AXI beat-FIFO stalls.
It completes with exact results, proving that pressure propagates rather than
allowing an unbounded host-side container to absorb responses.

## Remaining boundary

The dirty-mark loop has no fixed HLS pipeline II. Its per-unique-source bitmap
read/modify/write and list append currently remain explicit memory tasks after
the sorted source scan, rather than being interleaved with that scan. Carry
merge issue/consume, graph-write sub-pipelines, platform width conversion,
on-chip RAM port conflicts, and controller/CDC timing also remain separate
gaps. Therefore this milestone supports scan-pipeline and L0-II what-ifs, but it
does not yet make the entire maintenance kernel cycle-exact.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests -v
make -C cpp/sst -j2

python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 --no-build \
  --out-dir results/sst_spine_streamed_maintenance_amazon_bounded_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 --no-build \
  --maintenance-l0-write-scan-ii 1 \
  --out-dir results/sst_spine_streamed_maintenance_amazon_l0ii1_bounded_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot --no-build \
  --out-dir results/sst_spine_streamed_maintenance_carry_hot_bounded_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 --no-build \
  --maintenance-scan-response-capacity 2 \
  --out-dir results/sst_spine_streamed_maintenance_amazon_capacity2_20260724
```

Machine-readable evidence is in
`docs/evidence/spine_streamed_maintenance_scans_20260724_summary.json`.
