# Current-FPGA G+R Update Observability v13

## Scope

This revision adds one structured `update_observability` object to every
current G+R result mode. It exposes counters already produced by the
execution-driven update engine; it does not add timing, requests, buffering,
or scheduling behavior.

The object records:

- physical updates, record width, touched destination shards, and routes;
- insert/delete/weight-change classification;
- row, binary-search, cache, DDR, PMA, and degree activity;
- per-operation byte ledgers;
- degree FIFO occupancy and stalls;
- AXI request, backend, AXIS, and lane stalls; and
- update start/end cycles.

These counters are the candidate explanatory variables for the routed HLS
per-shard control envelope. They do not by themselves constitute a calibrated
timing model.

## Immutable plugin

- Path: `cpp/sst/build/sst-current-fpga-v13/libspine_cycle.so`
- SHA-256: `169548e16eb5eb6d2cecfe32c9fb04c90e0d16785dbcdceec7f8eb3e24625587`
- Parent behavior plugin: `sst-current-fpga-v12`
- Parent SHA-256: `f1fca617de22877ca675c72c6877444c029af8b83d4c30a25754d85f7e324b70`

## Non-interference validation

Three current-profile correctness-gated smokes were rerun with v13. Their
cycles and backend request ledgers exactly match the corresponding pre-v13
results.

| Algorithm | Total cycles | Update cycles | Compute cycles | Backend requests | Status |
|---|---:|---:|---:|---:|---|
| Weighted SSSP | 133,847 | 68 | 133,778 | 50,717 | PASS |
| Connected components | 133,857 | 70 | 133,786 | 50,741 | PASS |
| Thresholded residual PageRank | 1,487,890 | 199 | 1,487,690 | 997,048 | PASS |

Evidence roots:

- `/data/tmp/chuxiao/current_fpga_v13_observability_weighted_smoke_20260812`
- `/data/tmp/chuxiao/current_fpga_v13_observability_cc_smoke_20260812`
- `/data/tmp/chuxiao/current_fpga_v13_observability_residual_smoke_20260812`

The SSSP and CC comparisons use v12 resident-state smoke evidence. The
residual comparison uses the earlier behavior-equivalent smoke because the
observability-only change leaves the reported cycle and request ledger
identical.

## Claim boundary

The v13 counters make a routed control-envelope model auditable. Calibration
must still use AU/SU only, freeze all parameters before reading WK/R19, and
pass the existing transfer thresholds. A failed transfer row remains failed;
it must not be incorporated into fitting.

## Reproduction

```bash
make -C cpp/sst BUILD_DIR=build/sst-current-fpga-v13 -j8
sha256sum cpp/sst/build/sst-current-fpga-v13/libspine_cycle.so
```

All smoke commands must explicitly bind:

```text
--capability-catalog configs/contracts/grasu_regraph_sharded_k4_hls_capabilities_v8.json
--lib-dir cpp/sst/build/sst-current-fpga-v13
--no-build
```

Explicit capability binding is required because runner defaults are not part
of the immutable evidence identity.
