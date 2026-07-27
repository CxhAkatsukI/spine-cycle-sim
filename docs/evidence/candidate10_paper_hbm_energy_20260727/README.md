# Candidate10 Matched HBM Energy Figure

## Scope

This evidence derives a publication-facing HBM-only energy comparison from the
committed Candidate10 HLS-v3 matched energy ledgers. It covers weighted SSSP,
Full PageRank, and thresholded residual PageRank on three compact holdout
slices. Every run instantiates all 32 DRAMSim3 HBM controller instances. Spine
SSSP uses exact per-controller subtraction of a reproduced quiescent cold
prefix.

The plotted value is GraSU+ReGraph energy divided by Spine energy. Values above
one mean GraSU+ReGraph consumes more HBM energy.

| Algorithm | Total HBM | Command dynamic | Background + refresh |
|---|---:|---:|---:|
| Weighted SSSP | 1.006x | 3.779x | 0.993x |
| Full PageRank | 0.726x | 1.463x | 0.720x |
| Residual PageRank | 0.903x | 2.546x | 0.883x |

GraSU+ReGraph generates more command-dynamic HBM activity in all three
algorithms. Runtime-dependent background and refresh energy makes weighted
SSSP effectively tied in geometric mean, and lowers total HBM energy for the
two PageRank algorithms on these slices.

## Claim Boundary

This is not total accelerator, FPGA-board, or ASIC energy. Logic, FIFO,
interconnect, clock, host, PCIe, shell, and board energy are absent. Projected
CACTI SRAM energy is deliberately excluded because current on-chip component
coverage is asymmetric between the two architectures.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/analyze_candidate10_paper_energy.py \
  --out-dir docs/evidence/candidate10_paper_hbm_energy_20260727 \
  --paper-data-dir docs/paper/data
```
