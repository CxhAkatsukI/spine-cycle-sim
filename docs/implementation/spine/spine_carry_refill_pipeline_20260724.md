# Spine carry head/refill pipeline

Date: 2026-07-24

## Scope

This milestone replaces the maintenance carry model's fixed one-cycle-per-input
countdown and bulk level-edge read with a request-driven k-way head/refill
engine. The source reference is
`afb8199a2ca8d3fd208b985324bf4d8719e2b839` on
`origin/reduce-levels-for-routing`.

The latest HLS carry has one new-batch input and up to eleven lower-level
cursors. The new-batch input keeps one head. Each lower-level cursor keeps a
head and one lookahead entry. The minimum `(src,dst)` head wins; advancing a
winner synchronously refills its stream before the next merge decision.

The simulator now expresses that control dependency through actual AXI/HBM
requests. It no longer decrements a host-side counter while unrelated bulk
responses happen in the background.

## Execution model

For each family that carries into a target above L0, the maintenance component:

1. creates one new-batch stream and one stream for every occupied lower level;
2. scans the 128-bit sorted input on demand until the next edge belonging to
   that family is returned from HBM;
3. requests 64-bit old-level edge payloads one at a time and keeps at most two
   returned entries per lower-level stream;
4. waits until all initial heads/lookaheads and existing index requests have
   returned;
5. selects the minimum `(src,dst)` head, records one merge input, and refills
   only the winning stream;
6. coalesces equal keys, including differential cancellation and minimum
   weight selection, after all streams are exhausted.

Tie order is stable: new batch precedes ascending lower levels, matching the
HLS slot order. All response queues and memory requests use the existing finite
AXI/SST-HBM path.

New counters distinguish old-level payload reads from new-batch scans:

- `carry_level_payload_reads/bytes`
- `carry_new_batch_reads/bytes`
- `carry_refill_wait_cycles`
- `carry_max_buffered_heads`
- `carry_merge_inputs` and `carry_outputs`

The carry scan bytes are now included in total sorted-input bytes but not in
the streamed maintenance-pass beat count. This matches the source structure:
`partitioned_new_batch_next_for_family()` performs scalar reads between merge
iterations, not one streamed full-pass request.

## Validation

The focused L1 test has one new edge and one old-level edge. It records:

| Counter | Value |
| --- | ---: |
| New-batch reads | 1 edge / 16 bytes |
| Old-level reads | 1 edge / 8 bytes |
| Merge inputs / outputs | 2 / 2 |
| Maximum buffered heads | 2 |
| Refill/index wait | 83 cycles |

The L2 k-way test uses four new edges, two L0 edges, and two L1 edges. It
records eight merge inputs, eight outputs, 284 refill/index wait cycles, and a
maximum of five buffered heads: one new-batch head plus two entries for each of
the two lower levels. It verifies sorted output and retirement of L0 and L1.

The pre-existing anti-bypass test overwrites an old edge payload in HBM while
leaving the logical level state unchanged. The carried output observes the HBM
destination and weight, proving that old edge payloads remain memory
authoritative.

## SST-HBM evidence

| Model | Cycles | Backend requests | Sorted bytes | Carry refill wait | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Previous bulk/countdown | 8,402 | 1,899 | 1,152 | not modeled | exact |
| Request-driven refill | 8,402 | 1,901 | 1,184 | 114 | exact |

The two extra requests are the two raw sorted edges scanned by the cold carry
family. They add two DRAM reads and two activates in this placement. The total
does not change because this tiny carry work is hidden by a longer serial
critical path. The unchanged end-to-end total must not be interpreted as zero
carry cost; the component records 114 cycles in which carry cannot advance
while its memory chain is incomplete.

## Evidence tier and remaining boundary

This remains `structural_execution_driven`, not hardware-cycle calibrated.
The available carry csynth report contains stale internal module names that do
not exist in the pinned cursor-based source, so its aggregate min/max latency
is not used as a calibration constant.

This milestone closes winner/refill scheduling for new-batch and old edge
payloads. It does not yet close the full carry cursor or writer:

- old-level source IDs are still supplied by logical level state;
- bitmap, page-list, page-epoch, page-base, and row-offset reads are issued but
  their returned payloads do not yet drive cursor discovery;
- those index reads are pre-issued rather than requested exactly at cursor
  refill points;
- target bitmap/page-base/row-offset/mask/edge writes are still assembled and
  queued after the complete merge instead of overlapping each emitted group;
- epoch-wrap full-clear and malformed-index error paths need focused evidence.

Consequently, this result supports request-count, sorted-scan, head-capacity,
and refill-stall studies. It does not yet support a claim of cycle-exact carry
latency.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
build/cycle-core/cpp/spine_cycle_core_tests spine_cold_l1_carry
build/cycle-core/cpp/spine_cycle_core_tests spine_carry_kway_refill
build/cycle-core/cpp/spine_cycle_core_tests spine_carry_hbm_level_payload
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
make -C cpp/sst -j2

python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot --no-build \
  --out-dir results/sst_spine_carry_refill_carry_hot_20260724
```

Machine-readable evidence is in
`docs/evidence/spine_carry_refill_pipeline_20260724_summary.json`.
