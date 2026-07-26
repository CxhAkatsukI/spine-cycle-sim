# Candidate10 alignment collector inputs

This directory contains the minimal frozen simulator inputs needed by the L0
writer-schedule and AXI-adapter evidence collectors. The original generated
`results/` trees are intentionally ignored by Git; only the two A/B summaries,
three distinct matrices, and 11 pairs of per-case summaries used by the
collectors are retained here.

The files are copied byte-for-byte from the 2026-07-26 evidence runs in
`/home/chuxiao/spine-cycle-sim/results`. They make the default collectors and
their repository-consistency tests reproducible from a clean worktree.

```bash
sha256sum -c SHA256SUMS
python3 -m unittest \
  tests.test_candidate10_l0_writer_schedule_alignment \
  tests.test_candidate10_m_axi_adapter_alignment -v
```
