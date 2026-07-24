# Payload-backed memory foundation

Date: 2026-07-24  
Branch: `codex/fine-grained-cycle-sim`

## Scope

This milestone closes the payload gap in the shared memory transport, but does
not yet claim that every Spine component consumes memory-returned values.

The common path now carries data through:

`AxiRequest -> AXI burst/beat split -> MemoryBackend payload store ->`
`BackendResponse -> out-of-order beat placement -> AxiResponse`

Reads allocate a parent response buffer. Each returning beat is placed at its
original parent offset, so burst completion order cannot corrupt the payload.
Writes split their byte vector over the same beat and 4 KiB boundaries as the
timing request. A write becomes visible in the functional payload store when
the memory backend completes it, not when AXI submits it.

`MockMemoryBackend` and the SST adapter use the same `MemoryBackend` payload
contract. SST StandardMem plus DRAMSim3 determines request acceptance,
contention, and completion time. The common payload store supplies functional
data because DRAMSim3 is a timing model rather than an application data store.

Legacy callers may temporarily omit write data. AXI then explicitly zero-fills
the beat and increments `zero_filled_write_bytes`. Migrated critical paths must
show zero in this counter; omitted payload is therefore visible evidence, not
a silent success.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests

make -C cpp/sst -j2
python3 scripts/run_sst_payload_roundtrip.py \
  --out-dir results/sst_payload_roundtrip_formal_20260724 \
  --no-build
```

## Accepted evidence

The online SST test writes a deterministic 1,600-byte pattern beginning at
address 4,032, waits for completion, and reads it back. This crosses a 4 KiB
boundary and the configured AXI burst limit.

| counter | value |
| --- | ---: |
| core cycles | 62 |
| payload bytes written/read | 1,600 / 1,600 |
| AXI bursts / beats | 6 / 50 |
| backend requests | 50 |
| DRAM reads / writes | 25 / 25 |
| zero-filled write bytes | 0 |
| byte mismatches | 0 |

The AXI/backend/DRAM ledger closes exactly: `25 + 25 = 50`. The frozen summary
is `docs/evidence/sst_payload_roundtrip_20260724_summary.json`.

## Remaining work

The transport is payload-correct. Spine sorted input, vertex-state payload,
and emitted graph-edge payload have now been migrated in later milestones.
Metadata/index decisions and carry merge semantics still need to move away from
logical containers before Spine scenario results can be called payload-complete
rather than `structural_execution_driven`.
