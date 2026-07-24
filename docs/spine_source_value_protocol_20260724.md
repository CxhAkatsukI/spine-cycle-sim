# Spine source-value stream protocol

Date: 2026-07-24
Branch: `codex/fine-grained-cycle-sim`
HLS reference: `origin/reduce-levels-for-routing` at
`afb8199a2ca8d3fd208b985324bf4d8719e2b839`

## Scope

This milestone replaces the serialized request/reply shortcut on the
DEVICE_DIRTY path with the bounded two-stream protocol in the target HLS.
Protocol words use the same forward PartConv FIFO as tile and edge words. Value
responses and the terminal acknowledgement use the reverse FIFO.

The execution order is:

1. send at most 16 `SOURCE_VALUE_REQUEST` words, one per reader cycle;
2. drain the same number of ordered source/value responses;
3. repeat until all dirty sources are resolved;
4. send `SOURCE_COUNT`, `SOURCE_GENERATION`, and `SOURCE_REQUESTS_DONE`;
5. compute validates bounds, duplicate metadata, and request count;
6. compute returns one `SOURCE_REQUESTS_DONE` acknowledgement carrying the
   protocol status;
7. reader enters level lookup only after a successful acknowledgement.

The edge FIFO and reverse FIFO remain depth 32. They use the existing
evaluate/commit semantics, so requests cannot fall through in the same cycle
and HBM source-read latency can create real occupancy and backpressure.

## Error behavior

The compute status values follow the HLS ABI: `OK`, `UNEXPECTED`,
`SOURCE_BOUNDS`, `RESPONSE_SOURCE`, `COUNT`, `GENERATION`, and
`METADATA_DUPLICATE`. Reader-side response-source and ACK failures are mapped to
`DIRTY_STATUS_PROTOCOL_ERROR` and task error `PROTOCOL`.

The C++ `spine_source_protocol_error` test sends one request but reports a
source count of two. Compute returns a `COUNT` acknowledgement and finishes
with overflow/failure instead of accepting the malformed transcript.

## Window-boundary workload

`tests/data/source_protocol_window_17.slice` contains 17 distinct update
sources. It intentionally crosses the 16-credit boundary and is run through
both the mock backend and SST-DRAMSim3.

Required transcript:

- 17 source requests and 17 ordered responses;
- two request windows;
- three forward metadata markers;
- one reverse acknowledgement;
- 40 total forward words and 18 total reverse words;
- zero reader/compute protocol status;
- forward FIFO occupancy greater than one and no capacity violation.

The SST run reaches forward occupancy 14 of 32, proving that the first window
is queued while compute services source values through HBM.

## SST-DRAMSim3 evidence

All backend request counts close exactly against DRAM reads plus writes.

| scenario | cycles | requests | source windows | forward / reverse words | status |
| --- | ---: | ---: | ---: | ---: | ---: |
| Amazon L0 exact | 5,829 | 581 | 1 | 25 / 2 | 0 |
| carry + hot/cold | 6,277 | 649 | 1 | 10 / 2 | 0 |
| weighted SSSP, round 0 | 30,660 total | 2,636 total | 1 | 19 / 6 | 0 |
| 17-source window boundary | 8,133 | 813 | 2 | 40 / 18 | 0 |

The three small existing scenarios retain the same E2E cycle count even though
the stream transcript grows. In the current serial issue model the extra
control transfers fit into non-critical HBM wait intervals. The separate FIFO
ledger is therefore required; unchanged E2E time alone would not prove that
the protocol was modeled.

Frozen evidence:

- `docs/evidence/sst_spine_source_protocol_amazon_l0_20260724_summary.json`
- `docs/evidence/sst_spine_source_protocol_carry_hot_20260724_summary.json`
- `docs/evidence/sst_spine_source_protocol_weighted_sssp_20260724_summary.json`
- `docs/evidence/sst_spine_source_protocol_window17_20260724_summary.json`

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests

make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario protocol_window \
  --out-dir results/sst_spine_source_protocol_window17_20260724 \
  --no-build
```

## Remaining protocol gaps

This milestone models the source-value request window and its ACK. It does not
close the separate dirty-frontier ownership acknowledgement.

1. Reader task diagnostics and DONE overflow are not yet emitted and consumed
   as the complete HLS marker sequence on every error path.
2. A successful DEVICE_DIRTY run does not yet clear/advance the persistent
   dirty generation; HOST_ACTIVE coverage generation/hash metadata is not yet
   validated and acknowledged.
3. DEVICE_DIRTY correctly rejects more than 4096 sources, but the host handoff
   is not yet executed end to end.
4. HOST_ACTIVE exact-task overflow still reports failure instead of running the
   HLS tiled-reader fallback.
5. Source-value HBM reads are issued serially by compute. The finite stream
   window is exact, but AXI outstanding overlap remains a later timing phase.

The next protocol milestone is the diagnostic/DONE transcript plus dirty
ownership ACK, followed by HOST_ACTIVE fallback execution.
