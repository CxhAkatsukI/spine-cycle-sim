# Candidate10 Matched HBM Energy Figure

## Scope

This evidence derives a publication-facing HBM-only energy comparison from the
committed Candidate10 HLS-v3 matched PageRank ledger. It covers Full PageRank
and thresholded residual PageRank on three compact holdout slices. Every run
instantiates all 32 DRAMSim3 HBM controller instances.

The plotted value is GraSU+ReGraph energy divided by Spine energy. Values above
one mean GraSU+ReGraph consumes more HBM energy.

| Algorithm | Total HBM | Command dynamic | Background + refresh |
|---|---:|---:|---:|
| Full PageRank | 0.726x | 1.463x | 0.720x |
| Residual PageRank | 0.903x | 2.546x | 0.883x |

GraSU+ReGraph generates more command-dynamic HBM activity, but its shorter
PageRank execution reduces controller background and refresh energy enough to
lower total HBM energy on these slices.

## Claim Boundary

This is not total accelerator, FPGA-board, or ASIC energy. Logic, FIFO,
interconnect, clock, host, PCIe, shell, and board energy are absent. Projected
CACTI SRAM energy is deliberately excluded because current on-chip component
coverage is asymmetric between the two architectures.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/analyze_candidate10_paper_energy.py \
  --out-dir docs/evidence/candidate10_paper_hbm_energy_20260727 \
  --paper-data-dir docs/paper/data
```
