# Candidate10 Routed HLS Feasibility

## Scope

This bundle validates four U55C `hw` artifacts. Spine uses the latest
source-identical 152 MHz routed build; the three GraSU+ReGraph builds use a
150 MHz data-clock target:

- the native Candidate10 Spine weighted-SSSP core baseline;
- normalized, conversion-free GraSU+ReGraph weighted SSSP;
- normalized, conversion-free GraSU+ReGraph Full PageRank; and
- normalized, conversion-free GraSU+ReGraph thresholded residual PageRank.

`configs/evidence/candidate10_publication_ppa_v3.json` freezes each xclbin hash,
source identity, routed resources, linked CU multiplicities, HBM channels,
stream links, SLR assignments, and timing result. The analyzer fails closed if
any retained table or frozen expectation changes.

## Results

| Build | Target | LUT | REG | BRAM | URAM | DSP | WNS ns | Setup |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Spine SSSP | 152 MHz | 127,847 | 149,744 | 99 | 99 | 22 | +0.003 | closed |
| GraSU+ReGraph SSSP | 150 MHz | 96,559 | 107,380 | 233 | 64 | 0 | -0.013 | target missed |
| GraSU+ReGraph Full PR | 150 MHz | 178,374 | 177,836 | 278 | 64 | 304 | -0.130 | target missed |
| GraSU+ReGraph Residual PR | 150 MHz | 247,692 | 301,029 | 293 | 64 | 336 | -0.087 | target missed |

All four designs completed routing and produced an xclbin. Spine closes its
152 MHz target with +0.003 ns WNS. Its kernel source hash is byte-identical to
the earlier 150 MHz baseline, so this updates native feasibility evidence
without changing the frozen normalized 150 MHz simulator comparison. The three
GraSU+ReGraph builds are close to, but do not close, the 150 MHz setup target.
Their report-derived worst-path frequencies are approximately 149.71, 147.13,
and 148.07 MHz respectively. A generated xclbin is implementation-feasibility
evidence; it is not by itself evidence that the requested clock closed.

## Claim Boundary

These rows are not an iso-functional PPA comparison. The Spine artifact is its
native weighted-SSSP core baseline, while each GraSU+ReGraph row is a different
algorithm-specific normalized whole system. The ledger therefore sets
`resource_ratio_eligible` to false. The absolute numbers support feasibility
and implementation budgeting only.

This bundle closes routed area and timing evidence. It does not close dynamic
energy: that still requires correctness-gated simulator activity, HBM energy,
and validated per-component energy coefficients.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/analyze_publication_ppa.py \
  --manifest configs/evidence/candidate10_publication_ppa_v3.json \
  --out-dir docs/evidence/candidate10_publication_ppa_v3_20260727 \
  --paper-data-dir docs/paper/data
```

Expected output:

```text
PASS Candidate10 routed HLS feasibility: builds=4 resource_ratio_eligible=false
```
