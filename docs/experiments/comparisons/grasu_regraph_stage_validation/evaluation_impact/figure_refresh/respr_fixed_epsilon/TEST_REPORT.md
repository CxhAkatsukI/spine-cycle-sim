# Fixed-Epsilon ResPR Verification

## Passed Gates

- Fresh GCC 15.2.0 Release core and fresh SST experiment plugin build.
- Focused `routed_pagerank_tests` passes; all **39/39 CTests** pass in a
  separately frozen fresh core build. Sources remain unchanged during both
  numerical execution and core regression.
- Two small ResPR smoke arms and six AU/SU/WK arms pass final-state,
  residual-stopping, independent-oracle and request-ledger checks.
- Both core-library SHA256 hashes match the preceding strict-threshold
  run. The graph/batch and old/independent-oracle state hashes also match.
- **31 figure-refresh Python tests**, **6 threshold-follow-up tests** and
  **15 repository-structure tests** pass. These include explicit fixed versus
  legacy thresholds, rejecting changed model identities, preserving the
  nine-pair default gate, zero-active disclosure and stable CSV roundtrips.
- New evidence verifies offline, including every indexed member, raw
  result/configuration, full output state, all-32-channel energy sum, core
  regression and derived CSV. Archive SHA256:
  `33ef9f20aa7ba881d32117c94da5fc444a48997924188031c52dd9ac538ed4ca`.
- The prior nine-pair delivery also verifies unchanged. Its archive SHA256:
  `6b1a733173c3752fdd88c61e2e510ea0bc602fb8322d938f76d50f497e4898bb`.

## Resource Safety

The matrix ran in a 6-GiB max / 5-GiB high / zero-swap systemd service;
each child was limited to 4 GiB. Admission and the live-memory guard
preserved a 24-GiB system reserve. The saved live-memory record reports
2,800,312,320 peak bytes and zero swap; the largest individual process
reports 2,726,424 KiB RSS. The fresh core regression used the same finite
service limits and completed successfully. No FPGA job was launched.

Original outputs remain at
`/data/chuxiao/experiments/respr_fixed_epsilon_20261023/`.
The portable evidence archive retains their paths and identities; the
offline verifier does not require those original directories.

## Commands

From the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_figure_refresh*.py' -v
python3 -m unittest discover -s tests -p 'test_residual_threshold_followup.py' -v
python3 -m unittest discover -s tests -p 'test_repository_structure.py' -v
python3 scripts/audit_repository_structure.py --check-docs
python3 scripts/audit_repository_structure.py --check-catalogs
git diff --check
```

Use the README command to verify this delivery. The same command with
`multialgorithm.delivery` and output ending in `figure_refresh/multialgorithm`
verifies the old strict-threshold delivery.

To rerun the core gates, use a fresh output in the same bounded systemd
service shown in the README:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.core_gates \
  --output FRESH_CORE_GATES
```

## Interpretation Limits

These are device-cycle predictions, not host-inclusive Figure 8 timings,
new FPGA measurements or original-publication performance admission. All
three real batches have zero active correction seeds and unchanged rank
arrays at fixed epsilon: they do not validate general nonempty ResPR
propagation speedup. Their actual independent-oracle errors are retained;
the epsilon-dependent L1 bound is loose, not fixed global accuracy.
Spine correction still uses oracle-directed timed replay. The complete
Python suite was not rerun here and is not claimed green; previously
recorded unrelated suite failures remain unresolved.
