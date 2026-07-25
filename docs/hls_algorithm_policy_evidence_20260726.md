# HLS Algorithm Policy Evidence

The simulator and HLS evidence now share one explicit algorithm boundary:
source-map, edge-map/reduce, and apply. Weighted SSSP, Full PageRank, and
thresholded residual PageRank have byte-level float32/integer policy semantics
and an eight-lane HLS implementation at integration commit `15b92ed`.

![HLS algorithm evidence layers](figures/hls_algorithm_evidence_layers.svg)

## What Passed

- All three policy variants pass C++ functional tests against their expected
  state transitions.
- All three compile to Vitis 2024.1 `sw_emu` XOs at a requested 200 MHz clock.
- The PMA adapter passes legacy unit-weight, weighted full-word, and PageRank
  destination-only output tests.
- The normalized execution-driven simulator already runs all three algorithms
  with dual-oracle correctness checks.

## What This Does Not Yet Prove

The PageRank policy XOs are not complete GraSU + ReGraph accelerators. Full
PageRank still needs device dangling reduction, degree binding, rank ping-pong,
and whole-xclbin iteration control. Residual PageRank additionally needs rank
plus signed-residual storage and threshold frontier generation. Therefore their
current performance remains `normalized/proposed`, not `native`.

Weighted SSSP is farther along: the conversion-free complete xclbin passed
`sw_emu`, and its `hw` build is prepared under
`/data/tmp/chuxiao/grasu_regraph_weighted_sssp_native_hw_15b92ed_20260726`.

## Evidence Contract

The machine-readable status is
`configs/contracts/hls_algorithm_policy_evidence_v1.json`. Its tests verify
source hashes, the integration commit, all three algorithm entries, and
fail-closed native labels. Policy-core synthesis reports may be used only for
incremental arithmetic resource/latency comparison. Whole-system FPGA PPA
requires a linked and routed xclbin.
