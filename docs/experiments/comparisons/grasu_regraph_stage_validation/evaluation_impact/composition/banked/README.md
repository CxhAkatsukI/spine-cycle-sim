# Finite Search Across Runtime Banks

## Question

Can finite G search address independently placed row/binary metadata and hand
its updated physical PMA directly to R? This is a correctness/compatibility
step toward complete G integration, **not** an original-G performance match
or FPGA measurement. The preceding [handoff checkpoint](../README.md) used
direct G; the [finite performance checkpoint](../../search_pipeline/finite_model/README.md)
used co-located metadata and the full hot cache. Neither establishes their
combination in sharded memory.

## Change And Resource Contract

`SearchMetadataChannels` supplies optional row/binary channels. Each request
selects its bank through the existing AXI routing field. Missing overrides
retain fixed-channel behavior; invalid indices fail before traffic.
Each CU retains **one** shared metadata master, 32 aggregate parent/reply
credits, one issue/cycle, 64 workers and 339 internal FIFO channels. Split
banks do not create independent credit pools. Legacy flat parallel search
still rejects split banks. No timing multiplier, memory latency or original-G
control changes.

Production HLS connectivity permits both metadata pointers on HBM[0:22]. This
is topology context, not proof of the experimental finite pipeline's assumed
II or clock. Its separate HLS check remains pending. No production profile,
frozen SST library or bitstream is replaced.

## Declared Checks

- Distinct metadata banks and poisoned wrong banks prevent an ignored route
  from passing. Counts 0/1/63/64/65/129/257 run with/without backpressure and
  both registration orders. Invalid rows and out-of-range routes fail;
  requests, responses and FIFO drain are checked.
- Four handoff fixtures cover one/two/three shards, updated/untouched shards,
  reserved slots and an empty batch. Each has one unchanged-direct G control
  and two finite G registration orders: **12 runs, including 8 finite runs**.
- R starts with old-graph converged SSSP distances and a caller-prepared seed,
  scans G's updated physical PMA to quiescence, and equals independent
  new-graph Dijkstra at every vertex. No rebuild or hidden handoff traffic is
  allowed. R cycles/rounds/traffic equal the direct control. Finite registration
  order also preserves G cycles.
- The preceding **228 G observations** replay with exact complete-state
  hashes, cycles, counters and per-port diagnostics.
- A fresh Release core, **33 CTest targets**, SST build/load and two default
  SST numerical smokes check compatibility. Default handoff/search stdout
  must remain byte-identical. This is not finite/banked timing calibration.

The handoff fixtures retain cache sizes 1/8 and direct processors. They do
**not** enable the full 131072-segment/half cache behind the earlier
near-original-G prediction. Full cached sharded timing, realistic batch
distributions and high-source-ID controls need separate tests. These
tiny-edge graphs are not application-performance workloads.

## Observed Handoff

All 12 runs pass. The table lists each fixture once; finite forward/reverse
registration produces identical observations. Both arms use direct PMA
processors here. Latency is 7 cycles in the declared mock memory model.

| Vertices / shards | Cache segments/half | Batch | Direct G cycles | Finite G cycles | R cycles / rounds |
| --- | --- | --- | --- | --- | --- |
| 129 / 1 | 1 | Nonempty | 89 | 100 | 328805 / 5 |
| 65569 / 2 | 1 | Nonempty | 178 | 200 | 492645 / 5 |
| 131105 / 3 | 8 | Nonempty; third shard untouched | 178 | 200 | 656485 / 5 |
| 65569 / 2 | 1 | Empty | 0 | 0 | 98529 / 1 |

The finite search costs 11 additional cycles per updated shard in these tiny
batches. This overhead is retained, not subtracted or fitted away. R cycles,
rounds, read bytes and write bytes exactly match the direct controls. An empty
batch still runs R's final quiescence round; it is not reported as a speedup.

## Verified Delivery

The [evidence index](evidence/index.json) records all 12 handoffs and 12
bounded build/test/SST steps. The [raw archive](evidence/raw.tar.gz) preserves
pre-edit outputs, source snapshots, compiler flags, CTest and SST logs.
The [G replay index](evidence/g_replay/index.json) preserves all **228/228**
exact before/after observations, complete-state hashes and diagnostics, with
its own raw archive. No row failed or was removed.

All **33 CTest targets** and **114 focused Python tests** pass. The two
default SST smoke JSONs match their preceding checkpoint in every field.
These are default compatibility checks, not calibration of banked G timing.
Build/test peak per-process RSS was 1020068 KiB; matrix peak was 341284 KiB.
They are `wait4` per-process maxima, not simultaneous process-tree totals.
Additional delivery/Python logs are under `verification-v1/` in the raw root.

## Reproduction

Python owners: `composition/banked_analysis.py`, `banked_study.py`,
`banked_delivery.py`. Shared C++ execution: `cpp/tests/evaluation_impact/handoff/`.
Use fresh output paths:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.composition.banked_study \
  --output /path/to/new-attempt \
  --pre-edit /path/to/frozen-pre-edit \
  --previous-routed /path/to/frozen-default-routed.stdout.txt \
  --previous-matrix /path/to/finite-model/matrix-v1/results.json \
  --previous-sst /path/to/preceding-handoff/attempt-v2

python3 -m spine_cycle_sim.experiments.evaluation_impact.composition.banked_delivery \
  --report /path/to/new-attempt/results.json \
  --output /path/to/new-evidence \
  --pre-edit /path/to/frozen-pre-edit \
  --previous-matrix /path/to/finite-model/matrix-v1/results.json \
  --previous-sst /path/to/preceding-handoff/attempt-v2

python3 -m unittest tests.test_grasu_banked_handoff -v
```

Execution is serial, bounded by 2-GiB process address spaces and an 8-GiB
available-memory reserve; matrix children use 1 GiB. Builds use `-j1`.
Compiler, flags, inputs, source snapshots, complete states and diagnostics are
pinned. Larger queued jobs retain their higher safety gates. Raw root:
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-finite-banked-v1/`.

## Remaining Acceptance

Full cached sharded G, HLS/FPGA timing, original-publication matching, R
resource/credit controls, device seed/host accounting and a new Spine demo
remain separate gates. No Figure 7--11 replacement follows from a correctness
pass. The paper and frozen figure packages stay intact.
