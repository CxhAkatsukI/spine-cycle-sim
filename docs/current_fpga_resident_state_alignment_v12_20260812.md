# Current-FPGA resident-state alignment (v12)

## Scope

V12 corrects the GraSU+ReGraph SSSP and connected-components execution
boundary used by the current-FPGA calibration campaign. The routed FPGA hosts
accept one update batch while the old graph and converged algorithm state are
resident. They do not cold-start the final graph for every measured batch.

The architecture profiles, AU/SU calibration split, WK/R19 holdout split,
clock, HBM mapping, FIFO capacities, AXI parameters, and residual-PageRank
contract are unchanged from v11.

## Discovered mismatch

The rejected v11 matrix did the following:

- weighted SSSP initialized the source on the final graph and selected the
  cold-graph minimum superstep count;
- connected components passed `--hardware-full-recompute`, initializing every
  vertex with an active identity label.

The routed AU hardware evidence instead reports:

- weighted SSSP: `resident_state=old_graph_converged`, two supersteps;
- connected components: `resident_state=old_graph_converged`, one superstep.

V11 G+R SSSP/CC rows under
`/data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_20260812` are therefore
rejected. They may not be used for fitting, holdout validation, or figures.

## V12 behavior

Weighted SSSP now:

1. computes the converged old-graph distances independently;
2. admits only insertions and weight decreases, matching the routed host's
   resident mode;
3. maps unique logical update sources through the frozen host vertex reorder;
4. initializes ReGraph state from the old distances and activates only those
   sources;
5. requires the selected superstep count to equal the resident oracle and
   validates the final result against independent Dijkstra.

Connected components now uses the existing incremental setup: old-graph
component labels are resident and unique update endpoints are active. The
current calibration matrix no longer requests full recomputation. Deletion
fallback remains a separately labelled cold-identity path.

Residual PageRank already uses
`grasu_hardware_warm_dangling_linf`; no semantic change is made in v12.

## Immutable identities

- Plugin: `cpp/sst/build/sst-current-fpga-v12/libspine_cycle.so`
- SHA-256: `f1fca617de22877ca675c72c6877444c029af8b83d4c30a25754d85f7e324b70`
- Calibration contract:
  `configs/contracts/evaluation_refresh_fpga_calibration_v8.json`
- Case contract: `configs/contracts/evaluation_refresh_fpga_cases_v7.json`
- Evidence root:
  `/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812`

No v11 result is migrated into the v12 root. Calibration scales are fit only
after all AU/SU rows pass, committed before holdout, and then applied read-only
to WK/R19.

## Smoke evidence

The following execution-driven SST-HBM smokes use the immutable v12 plugin:

- weighted resident SSSP:
  `/data/tmp/chuxiao/current_fpga_v12_resident_weighted_smoke_v2_20260812`;
- resident connected components:
  `/data/tmp/chuxiao/current_fpga_v12_resident_cc_smoke_v2_20260812`.

Both pass correctness and memory-ledger validation. Weighted SSSP reports one
resident update source and three supersteps for the dynamic-shortcut fixture.
CC reports two resident update endpoints, rather than all eight vertices, and
three iterations for the bridge fixture.

## Reproduction

```bash
make -C cpp/sst BUILD_DIR=build/sst-current-fpga-v12 -j8
sha256sum cpp/sst/build/sst-current-fpga-v12/libspine_cycle.so

python3 -m unittest \
  tests.test_grasu_hls_weighted_runner \
  tests.test_current_fpga_grasu_frozen_matrix \
  tests.test_current_fpga_calibration_freeze
```
