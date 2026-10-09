# GraSU / ReGraph Publication-Match Study

## Decision

**The existing evidence does not establish a performance match within 10% of
the original GraSU or ReGraph publication.** This is a comparability finding,
not a measured slowdown and not a rejection of the newer FPGA figure matrix.
The missing controls must be implemented before assigning a numerical error.
No paper, figure, frozen calibration coefficient, or hardware artifact was changed.

This folder is the single review entry for the study. Start here, then inspect
the [source contract](../../../../configs/experiments/grasu_regraph_publication_match_v1.json),
[admission audit](publication_audit.json), and [fresh smoke report](smoke_report.json).
The smoke checks the Python validation extraction against an **older native
200-MHz port**, not the current 150-MHz sharded K4 figure data.

## What Is Established

| Check | Result | Meaning |
| --- | --- | --- |
| Documentation organization | 260 records relocated; topic guides and layout gates | Human navigation, not numerical-model validation |
| Runner validation extraction | Two before/after result JSON files exactly equal | Cycles, distances, traffic and stalls unchanged |
| Fresh native spread holdout | Correctness and structure pass; raw event-E2E error 53.40% | Unfitted old-port timing is not a 10% publication match |
| Fresh native star, 2 rounds | Rejected by mathematical oracle | Fixed iteration agreement is not convergence |
| Same star, 3 rounds | Correctness passes | Separate diagnostic; no comparison with the 2-round FPGA log |
| Original G and R publication controls | Not yet admitted | No publication-speed claim is available |

The preserved star rejection has zero architecture-oracle mismatches and one
mathematical mismatch: after two synchronous iterations the last vertex is
still unreached. A third iteration resolves it. Its failed run remains failed
in the raw campaign, and the historical matrix/logs are not rewritten.

The spread holdout uses a frozen FPGA log, not a fresh board measurement.
Its 578,499 simulated cycles at 200 MHz correspond to 2.892495 ms, versus
6.207438 ms in that old FPGA event window. The old measured-envelope fit is a
different layer; its reported small holdout error does not replace these raw
cycles or demonstrate original-publication performance.

## Source Findings That Change The Experiment

- **GraSU:** Table 4 reports 55.83--202.97 million successful edge updates/s
  on U250 at 200 MHz. Section 6.1 specifies 32 update PEs and 8-word PMA
  segments; hot edges use URAM. Our inspected K4 profile uses 16-word
  segments and direct HBM read-modify-write. The original cache kernel still
  contains URAM declarations, but our build defines
  `GRASU_PURE_PIPELINE_DIRECT_CACHE`; finding a URAM pragma alone proves nothing
  about the compiled path. These differences require measurement, not an
  assumed penalty or a fitted scale factor.
- **ReGraph algorithms:** its CC is *Closeness Centrality*, not our Connected
  Components. Weighted SSSP and residual PR are also not the paper's BFS and
  static PR. Full PR is the most direct common starting point, after verifying
  arithmetic, iteration and TEPS conventions.
- **ReGraph configurations:** `11L+3B` is an artifact example. Table IV uses
  graph-selected heterogeneous combinations. Figure 9 offers single-pipeline
  partition timings; Figure 12 includes 4-pipeline results. A four-pipeline
  mixed configuration is not automatically the all-Little `4L+0B` control.
- **Clock and denominator:** Figure 10 explicitly normalizes to 210 MHz.
  Do not silently apply that statement to another table or multiply a U55C
  result by a frequency ratio. Successful updates, trace events, traversed
  edges, unique edges, reciprocal edges, and physical PMA slots differ.

Sources: [GraSU paper](https://doi.org/10.1145/3431920.3439288),
[ReGraph camera-ready](https://soldierchen.github.io/assets/pdf/regraph.pdf),
[GraSU author repository](https://github.com/qgwang-hust/GraSU),
[ReGraph author repository](https://github.com/Xtra-Computing/ReGraph).
The contract records inspected source identities and exact table anchors.
No copyrighted paper is redistributed here. Remote HEADs are lookup identities,
not claims that our local port/source copy is an unmodified upstream checkout.

## Remaining Test Plan

| Order | Experiment | Required evidence |
| --- | --- | --- |
| 1 | Original-G control, isolated update stage | Original temporal AU trace, ten batches, PMA/hot-set policy, URAM and writeback model, same successful-update numerator and declared timing window |
| 2 | Original ReGraph A | Static PR on exact AM, original layout/DBG reorder and graph-selected configuration; verify published throughput/clock/iteration conventions first |
| 3 | Original ReGraph A4 | Four Little, zero Big with original reader and merger/apply resources; validate zero-Big generation and functional behavior, then compare with A separately |
| 4 | Adapter+R B | Same graph, vertex state, clock and resource budget as A4; expose PMA occupancy, padding, source traffic and reader backpressure |
| 5 | Complete G+R C | G followed by B plus separately measured host orchestration; a total-E2E agreement cannot hide compensating stage errors |

The original-G URAM control and independent original-ReGraph A/A4 component
models are **not implemented by this delivery**. Existing K4 parameters are
not a substitute for those models. New component code must have its own clear
ownership boundary; do not add another hidden mode to the large G+R unit.

For publication reproduction, predeclare calibration/holdout workloads before
fitting any timing parameter. The target is relative **rate** error no greater
than 10% on an admitted same-workload comparison, with neighboring cases and
all failures reported. Do not select the best row after observing results.
For A4/B, report the measured integration overhead rather than imposing a 10%
target: it is a resource-matched control, not a reproduction of a 14-pipeline
published score. Different platforms need an independently justified control,
not automatic frequency/bandwidth scaling.

Run correctness smokes first. Scale one process at a time until RSS is known;
the present campaign reserves 16 GiB, stops below 12 GiB and bounds each case
to 180 seconds. Full original hardware routing was not started. No fresh
large-graph or original-publication timing matrix was run in this delivery.

## Code And Reproduction

Canonical gates:
[native validation](../../../../spine_cycle_sim/experiments/grasu_native_validation.py),
[publication comparisons](../../../../spine_cycle_sim/experiments/publication_match.py).
The original native CLI imports/re-exports its validation functions; existing
callers remain compatible. Neither C++ numerical code nor the SST plugin changed.

Verification for this checkpoint: 86 focused Python tests passed; all four
C++ test executables passed in a separate GNU C++ 15.2.0 Release build.
The full Python suite, a new SST build, and a fresh FPGA matrix were not run.
The frozen plugin's own compiler identity is not inferred from the new CMake build.

```bash
python3 scripts/audit_grasu_regraph_publication.py \
  --contract configs/experiments/grasu_regraph_publication_match_v1.json \
  --out results/publication_audit.json

python3 -m unittest tests.test_publication_match tests.test_grasu_native_runner \
  tests.test_grasu_native_hw_matrix tests.test_grasu_native_hw_alignment \
  tests.test_grasu_native_timing_model tests.test_repository_structure

cmake -S . -B build/publication-validation -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build build/publication-validation --parallel 2
ctest --test-dir build/publication-validation --output-on-failure --timeout 120
```

The publication audit validates source hashes and comparison gates; its zero
matches means **no admitted timing match**, not four measured timing failures.
The full source contract includes unresolved conditions rather than filling
them from assumptions. Unit-test rates are fixtures, never research samples.

To repeat the two post-extraction SST runs with the existing frozen plugin:

```bash
timeout --signal=TERM --kill-after=10s 420s \
  python3 scripts/run_large_graph_campaign.py \
  --manifest configs/experiments/publication_validation_smoke_v1.json \
  --run-dir results/publication_validation_v1/campaign \
  --jobs 1 --large-jobs 1 --memory-reserve-gib 16 \
  --memory-emergency-gib 12 --memory-recovery-gib 16 \
  --sample-seconds 1 --no-pin-cpus
```

Use a fresh worktree/output location for a new campaign; the launcher preserves
existing state. This campaign intentionally retains the star rejection and
therefore exits nonzero. The results are not suitable for fitting a model.
Plugin SHA-256: `9a26e1fb51ecf7b99ccf0784c9e5bbc459cf857d293add557b9c52770b2c9d79`.
The plugin is not rebuilt by `--no-build`; it and the pinned HLS evidence must
exist locally. One-second RSS samples reached approximately 94 MiB per job;
these are sampled process-group values, not exact allocator peaks.

The [smoke report](smoke_report.json) hashes every packaged result, input and
log. It records resource settings and explicitly distinguishes refactor
equivalence, correctness admission, and timing evidence.

## Completion Boundary

Repository/documentation organization and the first behavior-preserving runner
extraction are complete. Source-based comparison gates and bounded regression
tests are delivered. The large C++/SST units still need incremental extraction.
**Original-publication performance matching remains unfinished**; no successful
10% claim, original URAM timing model, or Big-pipeline calibration is implied.
