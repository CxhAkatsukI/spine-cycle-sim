# Spine HOST tiled fallback and DEVICE handoff

Date: 2026-07-24
Branch: `codex/fine-grained-cycle-sim`
HLS reference: `origin/reduce-levels-for-routing` at
`afb8199a2ca8d3fd208b985324bf4d8719e2b839`

## Scope

This milestone closes the control-flow fallback paths of the current split
reader/compute HLS design. It does not replace an exact-path overflow with an
idealized graph traversal. The simulator now executes the same two-stage
DEVICE-to-HOST policy and the same tiled HOST work shape:

1. DEVICE_DIRTY reports `REQUIRES_HOST` when the dirty frontier exceeds 4,096,
   descriptor construction exceeds 65,536 tasks, or construction reads exceed
   1,048,576 edge payloads.
2. The host validates and recovers the generation-tagged dirty list, constructs
   the 16 destination-partition active bins, and restarts reader/compute in
   HOST_ACTIVE mode.
3. HOST_ACTIVE retries the exact path. Active-gate, task-capacity, and payload-
   budget overflow enter the tiled fallback instead of terminating.
4. For each non-empty destination partition, fallback first discovers touched
   64K-vertex tiles by rereading active records, metadata, bitmap/rank/page/row
   indexes, binary-searching HBM edge payloads, and reading range endpoints.
5. It then rereads every active record and row for every selected tile and
   replays the clipped HBM edge range through the finite PartConv AXIS FIFO.
6. If `active_records * discovered_tiles > 65,536`, all valid partition tiles
   are emitted with the force-dense bit. Compute immediately takes its full
   tile path and writes the whole tile back, matching the HLS fallback branch.

The four capacities are versioned `SpineL0Config` fields. Their defaults are
the production constants above. Unit and SST microbenchmarks may lower one
capacity to expose a boundary without generating a million-edge fixture; such
runs are explicitly threshold-scaled structural evidence, not production-
capacity performance measurements.

## Payload and timing authority

Fallback decisions are driven by returned HBM payloads:

- active-bin records are decoded from their 256-bit ABI;
- occupied/slice/page epoch, five level offsets, bitmap words, packed page base,
  and packed row offsets are reread through AXI;
- both binary lower bounds and endpoint checks decode level edge payloads;
- replayed edges are decoded again and checked against the current tile.

Every accelerator-side access above traverses `FixedAxiPort` and either the
deterministic mock backend or online SST memHierarchy/DRAMSim3 backend. AXIS
emission is capacity 32 and can backpressure the reader.

The current host handoff reads the dirty-list payload through backend
inspection and consumes zero simulated cycles. This is not hidden: every run
records `host_handoff_list_read_bytes`, `host_handoff_control_cycles=0`, and
`host_handoff_control_timed=0`. The failed DEVICE attempt is retained with its
own cycle count, and the accepted logical-round interval includes both DEVICE
and HOST kernel execution. Host DMA, launch, event wait, and bin-publication
time remain a separate required model.

## Anti-bypass tests

`spine_host_active_gate_fallback` uses 16,385 active records and five touched
tiles. The replay product crosses 65,536, so fallback expands to all six valid
tiles. It verifies 114,695 active-record reads, force-dense propagation, five
replayed HBM edges, six full compute tiles, and a two-pass vertex sweep.

`spine_device_dirty_host_handoff` creates 4,097 distinct dirty sources. It
verifies that DEVICE does not read the oversized list, HOST recovers all 4,097
IDs and exact identity, compute succeeds, and ACK clears all bits while
advancing generation 1 to 2.

`spine_convergence_4097_host_handoff` additionally separates algorithm and
execution evidence across that exact boundary. The first accepted logical
SSSP round keeps `active_in={0}`, while its physical `reader_sources` contains
all 4,097 dirty sources replayed by HOST_ACTIVE. Only the one destination
actually improved by source 0 enters the next logical frontier. The SST case
`syn_source_window_e4097__weighted_sssp` enforces the same distinction against
both synchronous-frontier and Dijkstra oracles.

`spine_device_task_limit_handoffs` lowers one threshold at a time. Both
descriptor-capacity reason 2 and payload-budget reason 3 must first produce a
recoverable DEVICE transcript and then complete the same three-edge HOST tiled
replay. `spine_convergence_host_handoff` proves that the reusable multi-round
runner preserves the failed attempt as evidence and converges automatically.

## SST evidence

Both formal cases use the same three-edge, three-tile workload and online
DRAMSim3 backend. The accepted SSSP result agrees with the independent
reference, all frontier mismatches are zero, and every backend request closes
against a completed DRAM read or write.

| scaled trigger | cycles | DEVICE attempt | backend requests | DRAM R/W | accepted paths |
| --- | ---: | ---: | ---: | ---: | --- |
| descriptor capacity = 2 | 14,771 | 4,617 | 1,424 | 1,316 / 108 | fallback, exact |
| payload budget = 2 | 14,708 | 4,584 | 1,418 | 1,310 / 108 | fallback, exact |

In both cases the HOST fallback performs four active-record reads, four exact
row lookups, three edge replays, and emits three fast-path tiles. The first
logical round includes the failed DEVICE attempt plus successful HOST kernel;
the unmeasured host control interval is disclosed separately.

Frozen evidence:

- `docs/evidence/sst_spine_fallback_capacity_20260724_summary.json`
- `docs/evidence/sst_spine_fallback_payload_20260724_summary.json`
- `docs/evidence/sst_spine_frontier_handoff_4097_20260725.json`

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests

make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario fallback_capacity \
  --out-dir results/sst_spine_fallback_capacity_repro \
  --no-build
python3 scripts/run_sst_spine_vertical.py \
  --scenario fallback_payload \
  --out-dir results/sst_spine_fallback_payload_repro \
  --no-build

python3 scripts/run_shared_comparison_matrix.py \
  --run-id syn_source_window_e4097__weighted_sssp \
  --system spine \
  --out-dir results/shared_frontier_fix_repro \
  --jobs 1 --timeout-seconds 1800 --no-build
```

## Claim boundary

This proves payload-driven fallback function, protocol shape, finite stream
behavior, and execution-driven accelerator memory traffic. It does not prove
production-threshold frequency, HLS-cycle equivalence, or complete E2E host
latency.

The reader currently issues one logical request at a time, so HLS loop
pipelines and outstanding overlap remain under-modeled. Descriptor, tile-state,
and active caches still use explicit cycle loops rather than wired BRAM/URAM
port conflicts. Those are the next timing-fidelity milestones.
