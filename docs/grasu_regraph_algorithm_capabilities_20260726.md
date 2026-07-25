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
| Normalized weighted | PMA-native | Absent by construction | Weighted SSSP; weighted dynamic SSSP | Simulation only |
| Normalized PageRank | PMA-native | Absent by construction | Full PageRank | Simulation only |
| Normalized residual | PMA-native | Absent by construction | Thresholded residual PageRank | Simulation only |
| Partitioned dynamic PageRank | Partitioned PMA-native | Absent by construction | Full PageRank with timed degree updates | Simulation only |
| Projected profiles | Parallel PMA-native | Absent by proposal | Profile descriptions only | Not executable |

The important negative result is explicit: the existing routed xclbin does not
implement weighted PMA words, Full PageRank, residual PageRank, or automatic
dynamic-SSSP fallback. Those algorithms cannot be labeled `native` merely
because they reuse the same simulator core.

## Enforced Invariants

The catalog loader checks all of the following before returning a capability:

1. Every GraSU/ReGraph architecture profile is covered exactly once.
2. The profile file SHA-256 matches the catalog entry.
3. `comparison_role`, PMA-native versus compacted handoff, and conversion-cost
   treatment agree with the architecture profile.
4. Every known algorithm is explicitly supported or unsupported; omission is
   an error.
5. `profile_only` projected designs fail an executable-capability request.

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
into native hardware. Closing that gap requires a compile-ready HLS path with
the weighted PMA ABI and a replaceable Map/Reduce/Apply policy, followed by
`sw_emu`, `hw_emu`, synthesis, and hardware correctness evidence. Until then,
the complete 73-pair comparison remains correctly labeled normalized and
conversion-free.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

python3 -m unittest \
  tests.test_profile_capabilities \
  tests.test_grasu_native_runner \
  tests.test_architecture_profiles

python3 scripts/run_sst_grasu_regraph_native.py --no-build \
  --out-dir results/native_capability_smoke_20260726
```
