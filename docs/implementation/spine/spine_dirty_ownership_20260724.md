# Spine dirty-frontier ownership lifecycle

Date: 2026-07-24
Branch: `codex/fine-grained-cycle-sim`
HLS reference: `origin/reduce-levels-for-routing` at
`afb8199a2ca8d3fd208b985324bf4d8719e2b839`

## Scope

This milestone closes the persistent dirty-frontier ownership path for one
successful update batch:

1. maintenance creates a generation-tagged dirty list, bitmap, count, and
   sum/xor identity;
2. DEVICE_DIRTY reader captures and validates that identity;
3. reader writes HLS-visible last-mode/status metadata and its 64-byte dirty
   result region before terminal diagnostics;
4. host publishes an ACK candidate only after reader and compute results agree;
5. the independent ACK_DIRTY component validates current and candidate
   identity, scans list/bitmap/hash, scans again to clear bitmap bits, advances
   generation, and writes its 384-byte result payload;
6. later HOST_ACTIVE rounds observe the cleared count and advanced generation.

All memory operations above are execution-driven requests through the same
finite AXI and online SST-DRAMSim3 backend as maintenance, reader, and compute.
No ACK validation or bitmap clear is implemented as a direct C++ state edit.

## Metadata ABI

`SpineMetadataLayout` now names every word in the HLS 16-word dirty block.

| offset | field |
| ---: | --- |
| +0..+3 | current count, generation, hash sum, hash xor |
| +4..+8 | candidate generation, count, hashes, valid |
| +9..+13 | host-coverage generation, count, hashes, valid |
| +14..+15 | last mode, last status |

HOST_ACTIVE reads both current identity and all five host-coverage words. A
non-empty dirty frontier is ACK eligible only when generation, count, both
hashes, and valid all match. A missing or partial handoff records
`COVERAGE_MISMATCH`; graph computation may still run, but ownership cannot be
released.

## ACK state machine

`SpineDirtyAck` implements the HLS order rather than an idealized clear:

1. publish four candidate identity words, then publish valid;
2. read current and candidate metadata;
3. reject invalid count, stale generation, or malformed identity without
   touching dirty bits;
4. validation pass: for every list entry, read one 128-bit list word and one
   128-bit bitmap word, check membership, and recompute both hashes;
5. clear pass: read every list entry again, then read/modify/write its 128-bit
   bitmap word;
6. on success write count zero, next nonzero generation, zero hashes, clear
   candidate/host valid, and record ACK mode/status;
7. write the exact 96-word ACK result payload, including overflow, path,
   layout versions, resulting identity, and candidate-valid evidence.

Stale and malformed ACK tests assert that bitmap bytes and generation remain
unchanged. The successful weighted test asserts the complete byte ledger:

| item | bytes |
| --- | ---: |
| host candidate publication | 40 |
| ACK metadata reads | 72 |
| ACK list reads, two passes over 5 sources | 160 |
| ACK bitmap reads, two passes over 5 sources | 160 |
| ACK bitmap writes | 80 |
| ACK metadata writes | 64 |
| ACK result write | 384 |

## SST evidence

Every accepted run has zero graph/SSSP mismatch and exact closure between
backend requests and DRAM reads plus writes.

The four frozen summaries were regenerated after the final SST plugin rebuild
and compared byte-for-byte with the accepted copies.

| scenario | cycles | backend requests | purpose |
| --- | ---: | ---: | --- |
| Amazon L0 exact | 5,860 | 584 | DEVICE_DIRTY reader result side effects |
| carry + hot/cold | 6,308 | 652 | independent cold carry and hot L0 path |
| 17-source boundary | 8,164 | 816 | two source-value request windows |
| weighted SSSP | 31,782 | 2,749 | six rounds plus full dirty ACK lifecycle |

In the weighted run, ACK_DIRTY takes 366 simulated core cycles. It validates
and clears five sources, changes `(count=5, generation=1)` to
`(count=0, generation=2)`, and all five later HOST_ACTIVE rounds independently
read `(0, 2)`. DRAMSim3 records 2,590 reads and 159 writes, exactly matching
the 2,749 backend requests.

Frozen evidence:

- `docs/evidence/sst_spine_dirty_ownership_amazon_20260724_summary.json`
- `docs/evidence/sst_spine_dirty_ownership_carry_20260724_summary.json`
- `docs/evidence/sst_spine_dirty_ownership_window17_20260724_summary.json`
- `docs/evidence/sst_spine_dirty_ownership_weighted_20260724_summary.json`

The architecture flow is in
`docs/figures/spine_exact_range_task_reader.svg`; its adjacent `.dot` file is
the editable source.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests

make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp \
  --out-dir results/sst_spine_dirty_ownership_repro \
  --no-build
```

## Claim boundary

This is structural, execution-driven evidence for one maintenance batch and
its convergence ownership closeout. It is not yet a complete runtime model.

- Maintenance is not yet restartable across multiple update batches, so
  accumulation into an already-owned dirty generation is not validated.
- Candidate writes are timed, but host result DMA, command launch, event waits,
  and HOST_ACTIVE buffer publication still lack measured host accounting.
- DEVICE_DIRTY above 4096 sources and HOST_ACTIVE exact-task overflow are now
  implemented by `docs/spine_host_tiled_fallback_20260724.md`. Host transfer
  and launch timing remains explicitly unmeasured.
- Reader and ACK issue one logical memory operation at a time. AXI supports
  bursts and finite outstanding requests, but producer-side overlap remains a
  timing gap.
- BRAM/URAM ports, arbitration, and bank conflicts for task caches are still
  represented by explicit cycle loops rather than reusable on-chip memories.
- Separate OpenCL buffers placed on the same HBM pseudo-channel do not yet have
  an explicit allocation/address-map model; this mainly affects row-locality
  and host-transfer claims.

Fallback execution was completed in the subsequent HOST tiled-fallback
milestone. The next timing priority is pipelined request issue plus explicit
on-chip memory arbitration.
