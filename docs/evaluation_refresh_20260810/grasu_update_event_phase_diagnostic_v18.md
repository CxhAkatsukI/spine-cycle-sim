# G+R Routed Update Event-Phase Diagnostic v18

## Scope

This evidence diagnoses the routed sharded-K4 GraSU update control window. It
does not fit or freeze a replacement calibration model. The twelve board runs
cover AU/SU/WK/R19 and weighted SSSP, connected components, and residual
PageRank. Every run targets `hw`, passes its algorithm oracle, and records the
host, xclbin, graph, run-log, and repository provenance in
`calibration_v18_grasu_update_event_diagnostic/analysis_manifest.json`.

The campaign contains 27 nonempty destination shards and 255 profiled update
CU events. For each shard it joins physical update layout counters with OpenCL
`QUEUED`, `SUBMIT`, `START`, and `END` timestamps for dispatch, two cache
processors, two DDR processors, four binary-search CUs, and the PageRank degree
CU where applicable.

## Result

The frozen v17 formula

```text
hardware_update_cycles = simulator_update_cycles
                       + constant_per_nonempty_shard * nonempty_shards
```

is not transferable. Its untouched diagnostic replay on WK/R19 has median
absolute errors of 37.28% (SSSP), 72.12% (CC), and 45.60% (residual PageRank).
Those rows were not refit or relabeled as holdout.

Across the 27 routed shard observations, update-event union time correlates
with allocated PMA slots (`R^2 = 0.878`), but much less with physical updates
(`R^2 = 0.180`), source segments (`R^2 = 0.089`), or binary probes
(`R^2 = 0.012`). This is a diagnostic correlation, not a mechanism model.

The routed xclbins were compiled with `GRASU_PURE_PIPELINE_DIRECT_CACHE` and
`GRASU_COMPACT_HBM_PORTS`. Their update HLS loops consume actual update records
and binary-search probes; they do not execute the legacy fixed-capacity cache
load/store sweep. Consequently, the PMA-slot correlation must not be described
as full-PMA update scanning. It can reflect routed memory placement, stream
producer/consumer lifetime, CU scheduling, or first-use runtime effects.

The event phases narrow the boundary further:

- `SUBMIT -> START` is negligible (normally below 0.002 ms).
- consumer CUs spend milliseconds in `QUEUED -> SUBMIT` while stream producers
  and routed resources become runnable;
- dispatch and cache/DDR CU execution spans include blocking stream lifetime,
  so summing CU event durations would double-count concurrent work;
- the per-shard union is therefore a routed device/runtime scheduling envelope,
  not an additive HLS-operation ledger.

## Claim Boundary

This package supports three claims only:

1. the old constant-per-shard update timing model fails to transfer;
2. the missing routed envelope is data/layout dependent; and
3. current evidence is sufficient to design a persistent same-process launch
   microbenchmark, but not to freeze a new timing equation.

It does not support attributing latency to a full-PMA scan, fitting WK/R19 as
holdout, or replacing the execution-driven FIFO/AXI/HBM model with a PMA-size
formula.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3
python3 scripts/analyze_grasu_update_event_phases.py \
  --evidence-root /data/tmp/chuxiao/grasu_update_event_phase_v2 \
  --out-dir docs/evaluation_refresh_20260810/calibration_v18_grasu_update_event_diagnostic
python3 -m unittest tests.test_analyze_grasu_update_event_phases
```
