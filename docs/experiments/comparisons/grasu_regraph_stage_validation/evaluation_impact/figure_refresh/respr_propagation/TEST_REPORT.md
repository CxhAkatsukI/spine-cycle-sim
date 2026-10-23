# Nonempty ResPR Verification

## Passed Gates

- A fresh GCC 15.2.0 Release core and fresh SST experiment plugin compile.
- The separate fresh Release build passes focused `routed_pagerank_tests`
  and all **39/39 CTests**. Sources remain unchanged during both numerical
  execution and core regression; their shared source identities agree.
- Two ResPR smoke arms and all six historical-input arms pass. Both sides
  share the old/oracle state hashes, use fixed FP32 `epsilon=1e-6`, meet the
  current independent oracle/residual gate and drain physical request ledgers.
- All three declared cases are retained, including all three Spine losses.
  Passive work counters reconcile reader/computed edges, active vertices and
  round CSVs. R scans exactly the updated graph's live edges times its rounds.
- **32 figure-refresh Python tests**, **10 residual-follow-up tests** and
  **15 repository-structure tests** pass. They cover fixed thresholds,
  historical input identities, missing scope, mismatched initial states,
  physical record counts, edge conservation and retaining negative outcomes.
- Portable verification regenerates JSON/CSV from archived raw records,
  validates full state identities, source snapshots, input hashes, numerical
  gates and all-32-channel DRAMSim3 aggregates. Archive SHA256:
  `18e1f442473c6ec6f4031902bc8621341d60e05117c211cd9c1952d1a0939630`.
- The previous fixed-threshold package verifies unchanged, with archive
  SHA256 `33ef9f20aa7ba881d32117c94da5fc444a48997924188031c52dd9ac538ed4ca`.

## Resource Safety

Both services used a 6-GiB maximum, 5-GiB high watermark and zero swap.
Children were bounded to 4 GiB, with atomic full-budget admission, a live
24-GiB system reserve and finite timeouts. No foreign job was changed.

The matrix completed in 2 minutes 6.5 seconds including builds and smokes.
Its saved cgroup peak is 974,151,680 bytes, with zero swap. The core service
completed in 11 minutes 41.3 seconds with a 920.4-MiB peak. The full CTest
phase took 375.2 seconds. These are host execution times, not device cycles.
No FPGA build or board job was launched.

## Checks

Run these from the repository root; use the README command for portable
verification of this package and `residual_followup` for the earlier one:

```bash
python3 -m unittest discover -s tests -p 'test_figure_refresh*.py'
python3 -m unittest discover -s tests -p 'test_residual*followup.py'
python3 -m unittest discover -s tests -p 'test_repository_structure.py'
python3 scripts/audit_repository_structure.py --check-docs
python3 scripts/audit_repository_structure.py --check-catalogs
git diff --check
```

The complete Python suite was not rerun and is not claimed green. This study
does not change the recorded unrelated suite failures or admit original-G/R
performance. The README details the oracle-directed correction and current
model boundary. The dense-Apply diagnosis is based on source and conserved
traffic, not new per-stage FPGA counters or a hardware timing fit.
