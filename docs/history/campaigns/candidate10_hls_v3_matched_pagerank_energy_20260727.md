# Candidate10 matched PageRank energy evidence

## Scope

This evidence compares Candidate10 normalized Spine and conversion-free
GraSU+ReGraph on the same three compact real graph slices, eight insertions,
150 MHz profile clock, Full PageRank and thresholded residual PageRank. Every
run instantiates all 32 U55C HBM pseudo-channel models. All 12 system runs and
all six matched pairs pass both correctness oracles and cross-system state
checks.

The source manifests are broader experiment manifests, so their generated
`complete_matrix` field is false. The selected energy subset itself is complete:
Amazon-2008, Web-Google, and soc-Flickr-und are present for both systems and
both algorithms.

## Matched HBM result

`GraSU energy / Spine energy` below is a ratio, so values below one favor
GraSU+ReGraph.

| algorithm | 32-channel HBM energy geo. ratio | command-dynamic geo. ratio |
| --- | ---: | ---: |
| Full PageRank | 0.726x | 1.463x |
| Thresholded residual PageRank | 0.903x | 2.546x |
| Combined | 0.809x | 1.930x |

The apparent reversal is expected. GraSU+ReGraph issues more memory activity,
so its command-dynamic energy is higher, but usually completes in fewer modeled
cycles; its accumulated HBM background and refresh energy is therefore lower.
The per-pair total-HBM ratio ranges from 0.636x to 1.247x, so the result is not
universal across workloads.

## On-chip boundary

The analysis also preserves CACTI-P estimates for GraSU source-property and
gather-temporary SRAM banks. Those arrays are projected 32 nm ASIC SRAMs, not
U55C BRAM/URAM. The corresponding Spine PageRank FIFO, pipeline, and on-chip
array activity is not yet characterized. Logic, AXI/interconnect, clock tree,
host, PCIe, shell, and board energy are omitted on both sides.

Consequently:

- the 32-controller DRAMSim3 HBM ratio is a matched simulator result;
- `partial_energy_pj` is an audit ledger, not a fair cross-system total;
- no total accelerator, FPGA board, or ASIC energy winner is claimed.

## Reproduction

The raw matrix tables and analysis outputs are frozen under
`docs/evidence/candidate10_hls_v3_matched_pagerank_energy_20260727`. Verify them
with:

```bash
cd docs/evidence/candidate10_hls_v3_matched_pagerank_energy_20260727
sha256sum -c SHA256SUMS
```

Re-run the analysis from the generated matrices with:

```bash
python3 scripts/analyze_matched_pagerank_energy.py \
  --full-dir <full-matrix-dir> \
  --residual-dir <residual-matrix-dir> \
  --out-dir <analysis-output-dir>
```

The command must print `PASS matched partial energy: systems=12 pairs=6`.
