# Routed FPGA area and timing evidence

Date: 2026-07-25

## Claim boundary

This milestone reports measured post-implementation U55C resource and timing
evidence for two native hardware systems:

- Spine from frozen revision `9c08763148644df262c0d374e782bc834f4c0f4f`;
- GraSU + ReGraph integration revision
  `a9aef064889faa190975ddfecb39c54631e962c6`.

The data is **native and non-normalized**. The GraSU + ReGraph build includes
the PMA-to-edge-array conversion kernel. The Spine build predates the current
`afb8199a2ca8d3fd208b985324bf4d8719e2b839` reference. No normalized or
projected architecture receives a measured area/timing label from these files.

All raw Vivado utilization/timing reports and xclbin metadata are archived as
gzip files. The manifest pins both archive SHA-256 and decompressed-content
SHA-256, records the source revision and full xclbin SHA-256, and the parser
rejects any report mismatch.

The accepted Spine utilization file is named `kernel_util_routed.rpt`, but its
own header says `Fully Placed`; the final timing report says `Physopt
postRoute`. Both states are preserved and checked verbatim instead of inferring
report state from the filename.

![FPGA evidence flow](/home/chuxiao/spine-cycle-sim/docs/figures/fpga_area_timing_evidence.svg)

## Primary results

`Used Resources` is the kernel resource total from each report; platform logic
is not included. Percentages are intentionally omitted from this table because
the two reports expose slightly different user budgets despite using the same
U55C platform.

| System | LUT | LUTAsMem | REG | BRAM | URAM | DSP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Spine accepted native | 123,707 | 11,605 | 144,033 | 92 | 99 | 34 |
| GraSU + ReGraph native | 99,404 | 13,492 | 115,954 | 248 | 64 | 0 |

Relative to GraSU + ReGraph native, this Spine build uses 24.45% more LUT,
24.22% more registers, and 54.69% more URAM, but 13.99% less LUT-as-memory and
62.90% less BRAM. GraSU + ReGraph uses no DSP while Spine uses 34. These are
per-resource observations, not a scalar FPGA-area ranking; the resource types
cannot be added as interchangeable units.

The component CSV keeps the hierarchy needed to explain those totals. For
example, the native conversion kernel alone contributes 9,911 LUT, 13,501
registers, and 39 BRAM to GraSU + ReGraph. Its cost is therefore visible rather
than silently removed.

## Timing interpretation

| Build | Requested | Achieved | Packaged | Kernel WNS/TNS at request | Disposition |
| --- | ---: | ---: | ---: | ---: | --- |
| Spine accepted `9c08763` | 150 MHz | 141.7 MHz | 141 MHz | -0.389 / -179.090 ns | accepted after auto-scaling |
| GraSU + ReGraph `a9aef06` | 200 MHz | 200 MHz | 200 MHz | +0.087 / 0 ns | requested clock closed |
| Spine canonical negative | 134 MHz | 134 MHz | 134 MHz | -0.252 / -0.252 ns | not closed at packaged clock |

The accepted Spine report does not close the requested 150 MHz constraint.
Vitis computes a 141.7 MHz achievable DATA clock and packages the xclbin at
141 MHz; the acceptance bundle identifies that auto-scaled route as the final
candidate. Conversely, the old canonical 134 MHz route still has negative
kernel setup slack while packaging 134 MHz. It remains negative evidence and
is not used as the primary Spine result.

Different packaged clocks do not establish end-to-end performance. Cycle
counts must be combined with the correct per-system packaged clock, and any
same-clock architectural comparison belongs to the normalized simulator
profile rather than this measured native table.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

python3 scripts/analyze_fpga_area_timing.py \
  --manifest configs/evidence/fpga_routed_native_20260725.json \
  --out-dir results/fpga_routed_native_20260725

python3 -m unittest -v tests.test_fpga_evidence
```

Expected output:

```text
PASS fpga_area_timing: spine_accepted_9c08763=packaged_after_auto_scaling grasu_regraph_native_a9aef06=requested_clock_closed spine_negative_9c08763_134=timing_not_closed_at_packaged_clock
```

The checked-in machine outputs are:

- `docs/evidence/fpga_routed_native_20260725/fpga_area_timing.json`;
- `docs/evidence/fpga_routed_native_20260725/fpga_summary.csv`;
- `docs/evidence/fpga_routed_native_20260725/fpga_components.csv`.

## Remaining work

- Route an HLS implementation matching current Spine revision `afb8199`.
- Synthesize and route the normalized conversion-free GraSU + ReGraph design.
- Add CACTI/on-chip-memory and logic activity energy; FPGA resources are not an
  energy model and DRAMSim3 energy covers HBM only.
- Run normalized scalability and dense-workload experiments before making a
  publication-level overall design comparison.
