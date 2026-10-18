# Historical A4 Model Versus Board

## Finding

The frozen A4 model and measured A4 control use identical CSR, initial state,
degree divisors and physical task payloads. Complete aligned outputs and
logical/physical work also agree. **This is functional identity, not an
admitted timing calibration or original-publication speed match.**

The audit independently rechecks eight model cases with two repetitions and
all eighteen A4 board runs. Only the nine `csr_degree` board runs match the
model's divisor binding. The nine `author_initial` runs remain checked but
are not numerical timing pairs. Each execution is one static fixed-point PR
superstep (`arg=0`), not residual PR or convergence.

| Input | Model cycles (210 MHz) | FPGA event-span cycles (150 MHz), median | Count ratio | FPGA event span (ms) | FPGA resident wall (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| boundary_ring | 113,714 | 204,417.00 | 0.556 | 1.362780 | 2.072270 |
| skewed_sources | 35,506 | 65,392.95 | 0.543 | 0.435953 | 0.936078 |
| amazon | 886,840 | 1,499,416.80 | 0.591 | 9.996112 | 12.538786 |

The count ratio divides two differently defined cycle counts. It is neither
a speedup nor a calibrated percentage error. There is no new fit, clock
conversion or latency adjustment in this audit.

## Why Timing Is Not Admitted

- The historical model contract is 210 MHz; the implemented board clock is
  independently admitted at 150 MHz. Memory latency in cycles is not made
  equivalent by multiplying all results by a clock ratio.
- The model uses declared mock memory, finite AXI resources and arbitration;
  these have not been calibrated to this specific routed A4 and its HBM path.
- Model tasks start on local drain. The board's earliest-start/latest-end
  event span includes real host task-launch gaps and scheduling effects.
  Overlapping event durations cannot simply be added or subtracted to infer
  the missing component times.

The model binary and all retained numerical captures remain hash-checked.
Twelve source-dependency paths have changed since the historical checkpoint;
the report records frozen and observed identities separately. No historical
artifact is rewritten, and the original strict delivery validator is not
relaxed. **The current model is not rebuilt or revalidated by this audit.**

These findings do not replace the pending actual `adapter + modified K4`
board control. A4 keeps the author's nine used HBM banks; four Little lanes
alone do not make it identical to the integrated 23-channel K4 layout.
No Spine speedup or replacement figure is admitted here.

## Evidence And Reproduction

The complete generated report is external, with its raw input/output and
source/binary identities. Files below are under:

`/data/chuxiao/experiments/baseline_hardware_validation_20261015/`

| Artifact | Relative path | SHA-256 |
| --- | --- | --- |
| Complete audit | `a4-model-board-audit-v2/results.json` | `3ca3dd92a32a5440cb58d0d08a7aaf6ec0506265840ddadbd691dce953be92a8` |
| Generated explanation | `a4-model-board-audit-v2/README.md` | `4d10822b00591bb5946c891b5963e68eb4f50203886056c64841cf8d509eda28` |
| Eighteen-row A4 board source | `a4-board-supervisor-v3/board/results.json` | `d5386df1306c0084840348ece4ba748fe6a528307f67a3f15f3423ac13f8dfab` |

The frozen model source is the study's existing `a4_results.json`,
`a4_verification.json` and
`configs/experiments/original_regraph_a4_execution_v1.json`. Raw captures are
still under `spine-cycle-sim-sharded-k4-v3/results/upstream_stage_controls/a4_execution_final_v3`.
Use the [owner's reproduction command](../../../../../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/board_execution/README.md#audit-the-historical-a4-model)
with a fresh output directory. The audit does not program a board.

Actual execution `a4-model-board-audit-execution-v2/` passed in a 2-GiB hard /
1-GiB high / zero-swap service on CPUs 124--125, with a 146.9-MiB peak and
4.855-second service duration. Six focused tests passed separately in
`a4-model-board-audit-tests-v4/`. They cover changed inputs, physical tasks,
outputs, work, repeats, clock, frozen binary, source drift and overwrite
rejection. These are software checks, not additional FPGA measurements.

The earlier strict attempt in `a4-model-board-audit-execution-v1/` rejected
changed historical source dependencies and remains retained. Test attempts
v1 (full `/tmp`) and v3 (incorrect test-wrapper import) also remain retained;
the successful tests use `/data/chuxiao/tmp`. Neither is a device failure.
