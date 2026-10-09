# Current-FPGA owner-port drain and vertical-ledger closure (v9)

Date: 2026-08-12

## Problem

The device-owner path can receive the source-completion marker immediately
after the final edge while cross-tile vertex writes are still in flight.  The
old simulator rejected this legal state as an overlapping owner-HBM protocol.
The real shared port instead drains those writes before issuing the owner
transaction.

## Repair

`SpineSplitSsspCompute::begin_owner_protocol()` now allows the owner state to
be entered with earlier write-only memory tasks outstanding.  The existing
`kOwnerProtocol` evaluation state stalls until those tasks drain and then
serializes the owner transaction on the same HBM port.

The `spine_vertical` and `spine_refactor31_probe` result paths now export and
fail closed on:

- one owner-round begin/finalize pair;
- reader and compute source-completion markers;
- source dispatch/completion equality;
- the independently recomputed owner request formula
  `2 + 7*dispatches + 6*completions + 8*activation_words + 9`;
- owner-HBM generated/completed/read/write request and byte ledgers;
- maintenance/reader/compute request closure;
- edge/value FIFO closure; and
- total backend request and byte closure.

A vertical probe intentionally stops after one algorithm round.  Its unretired
work credits therefore must equal the emitted next-frontier cardinality.  The
result records this as `single_round_next_frontier_residual`; complete E2E
runs still require global owner quiescence.

## Immutable plugin candidate

```text
cpp/sst/build/sst-current-fpga-v9/libspine_cycle.so
SHA-256 22a369e71e68b4e069371c11f6442274a05e21652499f98399e93fcc686666dd
```

Build and test:

```bash
make -C cpp/sst BUILD_DIR=build/sst-current-fpga-v9 -j8
cmake --build build/owner-protocol-v7 -j4
ctest --test-dir build/owner-protocol-v7 --output-on-failure
python3 -m unittest discover -s tests -q
```

RQ3 carry regression:

```bash
python3 scripts/run_rq3_carry_trace_matrix.py \
  --out-dir /data/tmp/chuxiao/evaluation_refresh_current_fpga_v9_rq3_20260812/carry-ledger-v2 \
  --target-level 1 --target-level 3 --target-level 5 \
  --lib-dir cpp/sst/build/sst-current-fpga-v9 \
  --profile configs/architectures/spine_owner_fifo_sssp_hls_v1.json \
  --no-build
```

All three cases pass.  L1/L3/L5 report respectively 11,331, 14,750, and
22,997 cycles, while all owner-round, owner-HBM, component-request, FIFO, and
backend-traffic ledgers close.  Their explained next-frontier residuals are
16, 64, and 256 work credits.

This v9 evidence supersedes the earlier v8 carry run.  It is not itself a
total-cycle calibration or holdout result.
