# GraSU/ReGraph native conversion baseline

Date: 2026-07-25

## Claim boundary

This document records the conversion-component milestone. The native ReGraph
edge-array compute pipeline and serial SST-HBM end-to-end controller were added
afterward; see `docs/grasu_regraph_native_e2e_20260725.md` for the current
status, exact-workload FPGA alignment, and timing claim boundary.

The two comparison paths are deliberately separate:

- `normalized`: weighted, destination-partitioned PMA words are consumed
  directly by the ReGraph model. No conversion cost exists.
- `native`: unit-weight GraSU raw-destination PMA words pass through the four
  completion tokens and the PMA-to-edge-array compactor. Conversion cost is
  explicit and must remain in any native end-to-end total.

`GraSuPmaWordAbi` and the compactor's payload guard enforce this distinction in
code. A normalized PMA word is rejected by the native compactor rather than
being silently interpreted as a raw destination.

## HLS mapping

Reference revision and artifact identity are pinned in
`configs/architectures/grasu_regraph_native_a9aef06.json`.

The implementation follows:

- `kernels/pma_completion_barrier/pma_completion_barrier.cpp`: four completion
  tokens are consumed in serial order.
- `kernels/pma_to_regraph_edge_array/pma_to_regraph_edge_array.cpp`: read the
  final row to bound total PMA slots; read every source row; scan every reserved
  16-slot segment; discard bit-31 empty slots; inject unit weight; write eight
  64-bit edges per 512-bit edge-array word; pad to `compact_edge_slots`.
- Vitis HLS 2024.1 synthesis report: `lane_loop` has trip count 16, achieved
  II=1, iteration latency 72 cycles, and enclosing module latency 88 cycles.
  The simulator exposes the 72-cycle value as an architecture parameter and
  then executes all 16 lane cycles.

The compactor issues actual `FixedAxiPort` row reads, PMA reads, and edge-array
writes to the shared `MemoryBackend`. Payloads, channel contention, finite AXI
queues, request completion, and output stalls therefore affect simulated time.
No measured millisecond value is hard-coded.

## Component ledger

`GraSuNativeCompactorCounters` reports:

- barrier token reads and cycles;
- row requests, including the HLS final-row pre-read;
- PMA segment requests and scanned slots;
- lane-pipeline cycles;
- valid, emitted, and dummy edge slots;
- edge-array writes;
- exact read/write bytes, AXI backend stalls, and output issue stalls;
- component start and end cycles.

For a completed run, the following identities must hold:

```text
row_read_bytes        = row_reads * 8
pma_read_bytes        = pma_segment_reads * 64
pma_slots_scanned     = pma_segment_reads * 16
edge_array_write_bytes = edge_array_writes * 64
emitted_edge_slots    = valid emitted edges + dummy_edge_slots
```

## Directed evidence

The directed native case contains 64 vertices, four initial edges, one delete,
and one insert. It uses the real update component before conversion, so the
compactor reads the PMA payload written by simulated hardware rather than a
host-reconstructed graph.

Observed ledger with the mock HBM backend:

```text
cycles=1119
barrier_cycles=4
row_reads=65
pma_segment_reads=3
pma_slots_scanned=48
valid_edges_seen=4
emitted_edge_slots=32
dummy_edge_slots=28
edge_array_writes=4
```

The decoded edge array exactly matches the post-update PMA oracle and every
output edge has unit weight. A separate negative test confirms that normalized
weighted PMA payloads fail the native ABI guard.

## Existing hardware anchor

The current hardware log
`/home/chuxiao/grasu-regraph-integration/results/pure_pipeline_hw_min32_wait_compactor_small_smoke/small_star_v4096_u1024.log`
records:

```text
vertices=4096
final_edges=5120
pma_scan_slots_once=66560
grasu_ms=1.290257
barrier_ms=0.046202
pma_compact_ms=3.598633
compute event union (hbm_ms)=0.735271
event_e2e_ms=5.907950
status=PASS
```

This is a later calibration/holdout anchor, not a fitted constant. Source,
xclbin, and routed-timing hashes must match the native architecture profile
before the measurement is used.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
cmake --build build/cycle-core -j2
./build/cycle-core/cpp/grasu_cycle_tests
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
cmake --build build/cycle-core-asan -j2
ctest --test-dir build/cycle-core-asan --output-on-failure
git diff --check
```

Expected directed markers include:

```text
PASS native_raw_pma_compactor
PASS native_compactor_abi_guard
```

## Follow-up status

The execution-driven edge-array reader, Gather/Merger/Apply path, serial
controller, closed ledger, and SST-HBM runner are complete. The remaining
native calibration gap is a multi-workload hardware matrix that independently
varies update count, source-row capacity, reserved PMA slots, compact slots,
and supersteps. The first exact-workload result is structurally exact but
underestimates the FPGA event end-to-end time by 49.38%, so it is explicitly
labeled trend-only rather than cycle calibrated.
