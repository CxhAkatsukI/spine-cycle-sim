# Actual Sharded-K4 Validation

This is the revised, production-path study. The preceding finite PMA+A4
control remains an independent layout/timing diagnostic, not a measurement
of this implementation. Neither its 74--791x predicted slowdown nor its
71-cycle memory assumption is assigned to the FPGA path.

Start with [the measured checkpoint and remaining work](RESULTS.md).
The [raw file index](raw_index.json) covers all 27 board logs and the
four candidate HLS ablations. It does not certify an optimized bitstream.

## Order And Acceptance

1. **Freeze and observe current hardware.** Preserve source, xclbin, graph,
   compiler and host identities. Run identical inputs with the baseline host,
   diagnostic host with tracing disabled, and diagnostic host with tracing
   enabled. Require unchanged result bytes, oracle admission, round counts,
   xclbin/input hashes and event dependency conservation.
2. **Confirm a bottleneck.** Inspect the routed build's HLS schedule together
   with event intervals. Kernel lifetimes include stream backpressure; they
   cannot by themselves isolate row-read stalls from downstream waits.
3. **Optimize the actual implementation and synchronize its simulator.**
   Change source-row reading only after identifying the relevant limitation.
   Preserve the old build. Require functional, RTL/synthesis, resource and
   board gates for any new bitstream; source tests alone are not FPGA evidence.
4. **Compare A4, current K4 and optimized K4.** Use the same graph, state,
   algorithm, iterations/convergence, clock and resident event boundary.
   List resource/port differences. A relative timing change includes layout,
   scheduling and backend changes, not solely adapter cost. Original-paper
   topology/platform reproduction is a separate gate.

SSSP/CC/ResPR production-hardware diagnostics are useful for stages 1--2;
they do not substitute for original ReGraph's one-iteration PageRank A4
comparison. The production FullPR host currently executes three rounds.
FullPR availability and matching arithmetic/initial state must be established
before the final A4 comparison is admitted.

## Owners And Reproduction

Production changes live in the integration repository. This simulator
repository owns the study runner, analysis, raw-evidence index and delivery.
The owner is `spine_cycle_sim/experiments/sharded_k4_stages/`; the CLI is
`scripts/run_sharded_k4_stage_diagnostic.py`. The host-only diagnostic is
opt-in through `GRASU_SHARDED_EVENT_TRACE=1`; timestamps are queried and
printed after the existing measured wall interval. Retaining event handles
inside that interval has a small potential host overhead, explicitly tested
by the three paired arms rather than assumed absent.

```bash
python3 scripts/run_sharded_k4_stage_diagnostic.py \
  --integration /home/chuxiao/grasu-regraph-integration \
  --matrix /home/chuxiao/grasu-regraph-integration/docs/evidence/sharded_k4_fullgraph_20260806/sssp_fullgraph_u55c/matrix.tsv \
  --case au_weighted_sssp_resident \
  --baseline-host /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/baseline_host/sharded_k4_sssp_native_host \
  --trace-host /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/trace_host/sharded_k4_sssp_native_host \
  --output results/sharded_k4_stages/au_unique_run --repeats 3 --device 0
```

The runner refuses to overwrite output, reserves 16 GiB of host memory,
limits each child to 8 GiB and 600 seconds, serializes its own board jobs,
and checks device occupancy before programming. It records inherited CPU
affinity and freezes both hosts plus the matrix-selected graph/xclbin.
Run failure logs are retained. The board lock coordinates this runner, not
other users; an occupancy failure must not be worked around by resetting
their board.

Candidate compile reproduction, without link or route:

```bash
python3 scripts/synthesize_sharded_k4_adapter_candidates.py \
  --integration /home/chuxiao/grasu-regraph-integration \
  --output results/sharded_k4_stages/fresh_synthesis
```

`GRASU_REGRAPH_ROW_PREFETCH=1` and `GRASU_REGRAPH_STOP_AFTER_LAST=1`
are independent, default-off HLS flags. The package stores original,
prefetch-only, stop-only and combined XOs at distinct local paths.
Only source functionality and HLS scheduling are admitted for those XOs.
The original routed xclbins remain unchanged.

Production diagnostic/candidate source is integration commit
`404797c` on `codex/sharded-k4-fullgraph-hls`. The raw package contains
`baseline_source.tar` and `candidate_source.tar.gz`, so the source checkpoint
does not depend on the current contents of another working directory.
`results.json` records a refined structured XML parse as
`delivery_report_analysis`; the initial HLS summary is kept intact and
hash-indexed rather than overwritten when handling nested latency ranges.

This checkpoint passed ten focused diagnostic/delivery tests, the six
earlier stage-delivery preservation tests, fifteen repository-structure tests,
four algorithm host builds/preparation gates and six legacy plus three
candidate adapter checks. The four HLS ablations pass. No full SST rebuild,
optimized RTL co-simulation, route, new-bitstream board run or eight-dataset
matrix was performed in this checkpoint.

Stage union, sum and compute span are reported separately. Do not add
overlapping adapter, gather, mux, apply and HBM durations as serial stages.
G retains the production host's existing update-event reporting. The new
trace covers compute kernels and PR source preparation, not internal AXI
transactions or ten exclusive Spine stages. Event gaps are not automatically
all host-orchestration cost, nor are total OpenCL lifetimes active compute.

## Initial Build Evidence

The original SSSP xclbin's Vitis 2024.1 report identifies a non-pipelined
`source_loop`, with iteration latency `77 ~ 536871061` cycles and a pipelined
inner `segment_loop`. This confirms a source-level scheduling limitation,
not a measured constant 77-cycle HBM latency or a proven whole-path slowdown.
The source baseline is integration commit
`67f38dc981bb5830474004c7921bd1d0c501a5fa`, archived before diagnostic edits at
`/data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/baseline_source.tar`.

Status: the initial AU three-algorithm hardware diagnosis is complete;
candidate packet equivalence and four HLS ablations pass. Stage 3 still
requires routing, board validation and simulator synchronization; no
optimized FPGA or final A4/K4 timing comparison has been accepted.
The existing figure handoff and paper are unchanged.
