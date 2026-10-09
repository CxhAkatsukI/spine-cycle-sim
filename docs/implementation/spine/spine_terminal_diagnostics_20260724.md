# Spine terminal diagnostic protocol

Status: historical diagnostic milestone. The fallback execution limitation
below was subsequently closed by
`docs/spine_host_tiled_fallback_20260724.md`.

Date: 2026-07-24
Branch: `codex/fine-grained-cycle-sim`
HLS reference: `origin/reduce-levels-for-routing` at
`afb8199a2ca8d3fd208b985324bf4d8719e2b839`

## Scope

The split reader now closes every architecturally handled success, fallback,
and task-error path with the exact HLS terminal stream shape. It emits ten
diagnostic words in this fixed order:

1. task status: path, fallback reason, and error packed into three bytes;
2. task count;
3. row lookups;
4. construction payloads;
5. replay payloads;
6. active records;
7. family probes;
8. family skips;
9. captured dirty count;
10. captured dirty generation.

One `DONE_ALL` word follows. Its payload bit 0 carries reader overflow. Compute
consumes every diagnostic, records it independently, folds `DONE_ALL` overflow
into its result, and only then drains its result/bitmap memory operations.

Previously, reader errors set `done` immediately. That could leave compute
blocked forever on the forward stream and hid the HLS-visible reason for the
failure. Architectural errors now enter a terminal state machine. If an error
is detected after `TILE_BEGIN`, the reader closes the tile before diagnostics,
so compute never observes a truncated tile transcript. Transport-level AXI
failure remains fatal because a failed memory response cannot supply a valid
HLS payload.

## Validation

The C++ metadata-format anti-bypass test corrupts only the HBM metadata control
word. The reader reports task path `ERROR`, task error `FORMAT`, emits exactly
ten diagnostics, and finishes with `DONE_ALL(overflow=1)`. This proves the
error path closes rather than silently stopping.

All successful online SST-DRAMSim3 runs require:

- exactly ten reader diagnostics and ten compute diagnostics per round;
- one reader and one compute DONE observation per round;
- zero DONE overflow;
- equality of all eight task fields plus dirty count/generation across the
  reader-to-compute boundary;
- backend accepted requests equal DRAM reads plus writes.

| scenario | cycles | forward words | rounds | diagnostic result |
| --- | ---: | ---: | ---: | --- |
| Amazon L0 exact | 5,839 | 35 | 1 | 10/10 fields match |
| carry + hot/cold | 6,287 | 20 | 1 | 10/10 fields match |
| weighted SSSP | 30,849 | `[29,16,15,15,14,11]` | 6 | all rounds match |
| 17-source window boundary | 8,143 | 50 | 1 | 10/10 fields match |

Compared with the preceding source-protocol evidence, each single-round case
gains exactly ten cycles and ten forward transfers. The weighted run gains ten
transfers in every round; its total timing also reflects changed inter-round
HBM row state, which is why the formal backend is run online rather than
replaying a fixed latency trace.

Frozen evidence:

- `docs/evidence/sst_spine_diagnostics_amazon_l0_20260724_summary.json`
- `docs/evidence/sst_spine_diagnostics_carry_hot_20260724_summary.json`
- `docs/evidence/sst_spine_diagnostics_weighted_sssp_20260724_summary.json`
- `docs/evidence/sst_spine_diagnostics_window17_20260724_summary.json`

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests

make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp \
  --out-dir results/sst_spine_diagnostics_weighted_20260724 \
  --no-build
```

## Claim boundary

This milestone closes the reader-to-compute terminal stream ABI. The follow-on
`docs/spine_dirty_ownership_20260724.md` milestone now closes HOST coverage,
candidate publication, ACK validation, bitmap clear, and generation advance
for one update batch. The two fallback execution paths, multi-batch update
orchestration, AXI outstanding overlap, and on-chip memory conflicts remain
timing or control-flow gaps.
