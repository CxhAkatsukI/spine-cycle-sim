# Candidate10 opt-v2 routed-HLS feasibility

This evidence replaces the old Spine routed anchor with the actual opt-v2
source-page working-set-cache implementation while retaining the frozen
three-algorithm GraSU+ReGraph routed evidence from v3.

- Spine source revision: `c338b323d95707b7b5a84f622795439004a7f013`
- Spine xclbin SHA256: `a6af7b51afbe2162b5d4fb624de5d4595b73690f1f6f3aee36211869f4bd38cc`
- Spine target / WNS: `150 MHz / +0.003 ns` (`target_closed`)
- Spine routed resources: `136437 LUT, 159403 REG, 95 BRAM, 115 URAM, 18 DSP`
- Ledger status: `PASS`

The four builds are not iso-functional: Spine is the native weighted-SSSP
core, while GraSU+ReGraph has separate conversion-free whole-system builds
for each algorithm. The ledger therefore disables cross-system resource
ratios and uses these reports only as implementation, resource, and timing
evidence.

Reproduce the ledger and paper-facing table:

```bash
python3 scripts/analyze_publication_ppa.py \
  --manifest configs/evidence/candidate10_publication_ppa_v4.json \
  --out-dir /tmp/candidate10-ppa-v4 \
  --paper-data-dir /tmp/candidate10-paper-data
```

Vivado's low-confidence automatic hierarchy-power report is kept separately
under `docs/evidence/candidate10_spine_opt_v2_vivado_power_20260728` so its
vectorless values cannot be confused with workload-calibrated simulator
energy.
