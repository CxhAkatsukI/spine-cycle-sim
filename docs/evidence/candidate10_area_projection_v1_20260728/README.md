# Candidate10 area footprint

This ledger reports complete routed U55C accelerator resource counts and an
explicitly partial 32 nm SRAM-capacity-equivalent projection for allocated
BRAM/URAM. The projected mm2 column is not full accelerator ASIC area: it
excludes logic, DSPs, interconnect, clocking, I/O, and macro-layout effects.

```bash
python3 scripts/analyze_area_projection.py \
  --out-dir /tmp/candidate10-area \
  --paper-data-dir /tmp/candidate10-paper-data
```
