# Spine carry level payload path

Date: 2026-07-24
Branch: `codex/fine-grained-cycle-sim`

## Scope

This milestone migrates the carried level-edge value payload used by Spine
maintenance cascade/carry merge.

Before this change, carry reads were timed through graph AXI/HBM, but merge
semantics still pulled the old edges from `SpineL0State` logical vectors. The
accepted path now is:

`existing level edge payload in graph HBM -> carry graph AXI read response ->
decode 64-bit CSR edge word -> carry merge -> target level graph write payload`

The simulator also initializes graph HBM edge payloads for any pre-existing
level state passed to `SpineL0Maintenance`, representing persistent graph state
that exists before the maintenance kernel starts.

## Accepted evidence

The C++ anti-bypass test `spine_carry_hbm_level_payload` proves the carry merge
uses returned HBM payload:

1. Logical initial cold L0 contains `src=0, dst=1, weight=5`.
2. The simulated HBM level payload is overwritten to
   `src=0, dst=4, weight=2`.
3. New sorted input contains `src=0, dst=2, weight=3`.
4. Maintenance carries L0 into L1.
5. The resulting L1 must contain destinations `2` and `4`, not the logical
   stale destination `1`.

Online SST carry/hot evidence:

| counter | value |
| --- | ---: |
| cycles | 4,805 |
| backend requests | 598 |
| carry payload reads | 1 edge |
| carry payload read bytes | 8 B |
| graph payload written | 24 B |
| reader graph payload read | 24 B |

Frozen summary:

- `docs/evidence/sst_spine_carry_payload_carry_hot_20260724_summary.json`

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest tests.test_sst_spine_vertical

make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot \
  --out-dir results/sst_spine_carry_payload_carry_hot_20260724 \
  --no-build
```

## Claim boundary

This closes the carry level-edge value payload bypass. It does not yet close
the whole carry/index path:

- source recovery for carried edges still follows the logical row/source order;
- level occupancy, row counts, page lists, bitmap probes, and metadata control
  decisions still consult logical containers or timed-only metadata reads;
- carry issue remains sequential through the current maintenance memory task
  queue rather than a fully pipelined/outstanding HLS loop.

The correct claim is still `structural_execution_driven`, now with sorted
input, carried edge payload, emitted graph-edge payload, and vertex-state
payload all backed by simulated HBM responses on the accepted vertical paths.
