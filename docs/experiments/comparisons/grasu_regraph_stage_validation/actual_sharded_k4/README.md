# Actual Sharded-K4 Validation

This is the revised, production-path study. The preceding finite PMA+A4
control remains an independent layout/timing diagnostic, not a measurement
of this implementation. Neither its 74--791x predicted slowdown nor its
71-cycle memory assumption is assigned to the FPGA path.

## Current Status

The [optional weighted-SSSP A4 control](matched_a4/sssp_control/README.md)
now supplies a same-arithmetic building block instead of comparing original
fixed-point PR with production SSSP. It checks complete padded resident-round
states and replica acknowledgements. This is a local UDF correctness gate;
matched whole-graph inputs, SSSP timing and A4/K4 performance remain open.

The [controlled initial-residency checkpoint](model_sync/sst/input_residency/README.md)
now retains all 30 complete outputs and rounds. XRT traces expose 16 late
WK row-table transfers inside the previous compute window; explicit initial
migration before updates removes the observed transfers. All six unchanged
v4 model predictions then differ nominally from three-repeat resident FPGA
medians by -6.40% to +1.69%. Initial migration is separately timed, not free.
This advances aggregate-window validation without admitting exclusive
stages, other algorithms, or the still-pending original-A4 comparison.

The [complete v4 real-graph matrix](model_sync/sst/empty_exit_matrix/README.md)
now passes all six AU/SU/WK old/optimized full-output and traffic checks;
all six v3 replays are byte-identical. Five nominal predicted compute spans
differ from FPGA spans by -3.79% to +1.37%; optimized WK remains -35.04%.
These are not identical-window calibration errors. The per-invocation trace
exposes same-CU scheduling gaps absent from the model, without establishing
their root cause or adding a fitted delay. Whole-path timing and original-A4
matching remain open.

The [nine-run CPU-affinity control](model_sync/sst/dispatch_affinity/README.md)
preserves all complete WK outputs. Expanding the unchanged host from two to
eight or 32 allowed CPUs leaves median spans at 94.32, 92.47 and 95.48 ms;
it does not close the 60.16-ms model prediction. Same-CU gaps remain despite
early enqueueing. That negative control motivates the later runtime trace
and residency intervention above; it does not itself establish the cause.

The [RTL empty-exit model control](model_sync/sst/empty_exit_model/README.md)
now represents a measured 73-clock generated-RTL wait for each actually
visited empty row. Across four fixed-payload sizes, old-adapter lifetime
predictions differ from FPGA medians by -1.75% to +1.35%, without fitting.
Five legacy cases and eight old sweep replays remain exact; eight v4 runs
retain full FPGA outputs and traffic. The optimized short control still has
a large timing gap. This is a local result, not whole-system calibration.
The [occupied-row helper probe](model_sync/sst/occupied_row_rtl/README.md)
also shows that the 73-clock empty exit must not be appended after each
occupied row's final packet; helper pipeline delay overlaps output.

The [routed stream-capacity correction](model_sync/sst/routed_streams/README.md)
matches all 19 inter-kernel FIFO connections in both measured builds. Its six
old/new runs preserve full FPGA results and traffic; total cycles change by
at most 0.101%. This fixes a structural mismatch, not the timing gap.

The preceding [controlled empty-row study](model_sync/sst/empty_rows/README.md)
isolated the timing lead: 24 board and eight fixed-model runs preserve the live
graph and PMA while extending only empty source rows. The old FPGA adds
981--993 ns per empty row; the model adds 520 ns. The optimized adapter removes
trailing-row scaling. Its frozen v2 results are not overwritten by v4.

## Evidence Trail

The [initial measured checkpoint](RESULTS.md) remains a historical baseline.
Continue with [adapter RTL/route validation](adapter_optimization/README.md)
and the [paired SSSP board results](adapter_optimization/BOARD_RESULTS.md):
AU/SU/WK now pass all 18 old/new executions, with measured setup-inclusive
improvements of 9.82x, 8.30x and 52.63x. Production-simulator synchronization,
other optimized algorithms and matched original-A4 performance remain open.
The [model synchronization checkpoint](model_sync/README.md) records the
behavior-preserving reader extraction and new shared-master adapter tests;
it does not claim complete system integration or timing calibration.
The next [compute/port checkpoint](model_sync/compute_ports/README.md) extracts
the compute stages and validates finite shared-master clients with their
arithmetic, while retaining the same open system/timing gates.
The [frontend checkpoint](model_sync/frontend/README.md) adds connected
Scatter/source gates and an important binary-identity correction: measured
SSSP retains four independent source masters; the later HLS worktree uses
two pairwise masters. Calibration must follow the measured XO, not that
later source file. Whole-system scheduling and timing remain open.
Subsequent [complete composition](model_sync/system/README.md) and
[explicit SST diagnostic](model_sync/sst/README.md) checkpoints connect that
measured topology and admit HLS-exported full-state/traffic checks. Hardware
timing admission and original-A4 performance matching remain open.
The subsequent [independent-channel correction](model_sync/sst/independent_channels/README.md)
preserves all five legacy results and all six v1 matrix rows exactly, while
all six explicit-v2 runs pass full FPGA output equality and conservation.
It corrects a demonstrated read/write dependency, but nominal times still
underpredict the board span; it is not timing admission or an A4 match.
The initial raw package below remains
frozen and does not contain the later candidate build.
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
before that PR comparison is admitted. The separate local weighted-SSSP
control above offers another same-algorithm route, without claiming a
published ReGraph SSSP workload or inheriting the PR timing acceptance.

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

Status of the initial frozen checkpoint: the AU three-algorithm hardware diagnosis is complete;
candidate packet equivalence and four HLS ablations pass. Stage 3 still
requires routing, board validation and simulator synchronization; no
optimized FPGA or final A4/K4 timing comparison was accepted in that initial package.
The later candidate SSSP board acceptance is documented in the linked
`adapter_optimization` package; it does not rewrite the initial evidence.
The existing figure handoff and paper are unchanged.
