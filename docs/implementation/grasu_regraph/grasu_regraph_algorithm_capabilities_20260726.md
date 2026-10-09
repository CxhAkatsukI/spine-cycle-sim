# GraSU/ReGraph Algorithm Capability Contract

Date: 2026-07-26

## Purpose

The simulator contains several GraSU/ReGraph implementations with different
hardware relationships. A shared Map/Reduce interface does not make those
implementations interchangeable evidence. This milestone adds a hash-pinned,
fail-closed catalog at
`configs/contracts/grasu_regraph_capabilities_v1.json` so a runner cannot
silently execute an algorithm under a profile that does not implement it.

## Current Boundary

| Profile class | Handoff | Conversion | Executable algorithms | Claim boundary |
| --- | --- | --- | --- | --- |
| Existing HLS native `a9aef06` | PMA -> compactor -> edge array | Included | Unit-weight SSSP | Hardware-aligned structure; fixed host supersteps |
| Weighted HLS-aligned `ff13a67` | Full-word PMA -> 8-lane AXIS | Absent | Weighted SSSP; weighted dynamic SSSP | `sw_emu` correctness plus execution-driven SST; not cycle-calibrated |
| Normalized weighted | PMA-native | Absent by construction | Weighted SSSP; weighted dynamic SSSP | Simulation only |
| Normalized PageRank | PMA-native | Absent by construction | Full PageRank | Simulation only |
| Normalized residual | PMA-native | Absent by construction | Thresholded residual PageRank | Simulation only |
| Partitioned dynamic PageRank | Partitioned PMA-native | Absent by construction | Full PageRank with timed degree updates | Simulation only |
| Projected profiles | Parallel PMA-native | Absent by proposal | Profile descriptions only | Not executable |

The old routed xclbin still does not implement weighted PMA words, Full
PageRank, residual PageRank, or automatic dynamic-SSSP fallback. Revision
`ff13a67` closes only the first hardware gap: weighted full-word PMA update and
conversion-free fixed-round weighted SSSP pass `sw_emu`. The separate
`grasu_regraph_hls_weighted_sssp` simulator mode now implements full-word
lookup, physical update lowering/reorder, eight lanes, and fixed host rounds.
The older normalized mode deliberately keeps destination-keyed replacement and
quiescence semantics and must not be presented as the HLS-emulated profile.

## Enforced Invariants

The catalog loader checks all of the following before returning a capability:

1. Every GraSU/ReGraph architecture profile is covered exactly once.
2. The profile file SHA-256 matches the catalog entry.
3. `comparison_role`, PMA-native versus compacted handoff, and conversion-cost
   treatment agree with the architecture profile.
4. Every known algorithm is explicitly supported or unsupported; omission is
   an error.
5. `profile_only` projected designs fail an executable-capability request.
6. The weighted HLS runner requires an executable weighted-dynamic-SSSP
   capability and validates the full-word ABI before launching SST.

`scripts/run_sst_grasu_regraph_native.py` now requires the executable
`unit_weight_sssp` capability before launching SST. Its output manifest embeds
the algorithm record plus the capability-catalog path and SHA-256.

The recorded SST smoke at
`docs/evidence/grasu_regraph_native_capability_smoke_20260726.json` closes with:

```text
cycles                         99884
correctness_mismatches             0
conversion_cost_included        true
algorithm           unit_weight_sssp
profile SHA-256     ca47981158689d995973992df47ed659aa886b5b1a71ac99f468a0361f72adaf
catalog SHA-256     41b561a5946e4b26fffd7911a95210a827efd5ebc2189a8c3e9edc4246f567fb
```

This is a structural smoke, not a new hardware calibration point.

## What This Does Not Implement

This contract prevents claim leakage; it does not turn normalized algorithms
into native hardware. Weighted fixed-round SSSP now has a compile-ready HLS
path, `sw_emu` evidence, and an execution-driven SST mode. The remaining steps
are broader dual-oracle workloads, `hw_emu`, synthesis/routing, and hardware
timing comparison. Full and residual PageRank still require matching
HLS-aligned policies.
Until then, the complete 73-pair comparison remains correctly labeled
normalized and conversion-free.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

python3 -m unittest \
  tests.test_profile_capabilities \
  tests.test_grasu_hls_weighted_runner \
  tests.test_grasu_native_runner \
  tests.test_architecture_profiles

python3 scripts/run_sst_grasu_regraph_native.py --no-build \
  --out-dir results/native_capability_smoke_20260726

python3 scripts/run_sst_grasu_regraph_hls_weighted.py --no-build \
  --out-dir results/grasu_regraph_hls_weighted_ff13a67_20260726
```
