# Spine sorted input payload path

Date: 2026-07-24
Branch: `codex/fine-grained-cycle-sim`

## Scope

This milestone migrates Spine maintenance's sorted-edge input buffer from a
logical workload bypass to simulated HBM payload.

The accepted path is now:

`host-prepared sorted edge buffer -> sorted_edges AXI read -> MemoryBackend/SST
payload store -> AxiResponse -> SpineL0Maintenance scan/coalesce`

The host preparation is modeled as an excluded initialization step: the sorted
buffer is present before the kernel starts. Host transfer time is still outside
this milestone and remains part of the measured host-round accounting gap.

## Encoding

The sorted input uses the HLS `edge_entry_t` layout from
`common_types.hpp`:

| bits | field |
| --- | --- |
| 127:96 | `src` |
| 95:64 | `dst` |
| 47:32 | `weight` |
| 15:0 | signed `diff` bits |

This is a 128-bit sorted input record. It is intentionally different from the
64-bit level CSR record, which omits `src` because the reader recovers source
from the CSR row.

## Accepted evidence

The C++ anti-bypass test `spine_maintenance_hbm_sorted_payload` proves that
maintenance consumes the sorted HBM payload:

1. Construct the maintenance workload with one logical edge:
   `src=0, dst=1, weight=5`.
2. Before the kernel runs, overwrite only the sorted-edge HBM payload with:
   `src=0, dst=2, weight=2`.
3. Run maintenance to completion.
4. Require the persisted cold L0 level to contain `dst=2, weight=2`.

A maintenance model that still used `workload_.edges` would persist
`dst=1, weight=5` and fail.

Online SST evidence was regenerated for the three small accepted Spine
vertical scenarios:

| scenario | cycles | backend requests | sorted bytes | sorted payload read |
| --- | ---: | ---: | ---: | ---: |
| Amazon L0 exact | 4,608 | 545 | 3,040 B | 3,040 B |
| carry + hot | 4,805 | 598 | 1,120 B | 1,120 B |
| weighted SSSP | 22,630 | 2,412 | 2,432 B | 2,432 B |

Frozen summaries:

- `docs/evidence/sst_spine_sorted_payload_amazon_l0_20260724_summary.json`
- `docs/evidence/sst_spine_sorted_payload_carry_hot_20260724_summary.json`
- `docs/evidence/sst_spine_sorted_payload_weighted_sssp_20260724_summary.json`

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest tests.test_sst_spine_vertical

make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 \
  --out-dir results/sst_spine_sorted_payload_amazon_l0_20260724 \
  --no-build
python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot \
  --out-dir results/sst_spine_sorted_payload_carry_hot_20260724 \
  --no-build
python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp \
  --out-dir results/sst_spine_sorted_payload_weighted_sssp_20260724 \
  --no-build
```

## Claim boundary

This closes the sorted input value bypass for the accepted maintenance paths.
Together with the vertex-state and graph-edge milestones, the current Spine
vertical prototype now consumes payload for:

- sorted batch input records;
- emitted level edge records;
- vertex-state reads and writes.

The simulator is still not payload-complete. Remaining logical-container
dependencies include:

- level occupancy and row enumeration in the reader;
- metadata/index bit decoding for control decisions;
- carry merge semantics over pre-existing levels;
- measured host-round transfer and launch accounting.

The correct claim remains `structural_execution_driven` with major data
payload paths closed, not full HLS-cycle equivalence.
