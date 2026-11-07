# FPGA Cycle Validation: Warm SSSP Pilot

This is a **limited device-cycle validation**, not a replacement for Figures
7--11 or a calibration of every algorithm and stage. The paper is unchanged.

- [Preview](data/figures/fpga_cycle_validation.png) / [vector PDF](data/figures/fpga_cycle_validation.pdf)
- [Six paired rows](data/cycles.csv) / [summary](data/summary.json)
- [Complete data and code zip](fpga_cycle_validation_data_code.zip)
- [Provenance](provenance.json), [file hashes](manifest.json),
  [unchanged-default regression](zero_override_regression.json)

## Result

All four predeclared holdouts pass the **per-point absolute error <=20%**
criterion. Their maximum error is **15.69%**, median **8.20%**. Each case has
one FPGA measurement, not repeated samples or an uncertainty estimate.
CPU-reference checks and the exact per-round edge/source/task checks pass.

| Case | Role | V / initial E | Rounds | Measured cycles | Simulated cycles | Absolute error |
| --- | --- | --- | --- | --- | --- | --- |
| dev_narrow | Development | 256 / 18 | 4 | 228,411 | 214,676 | 6.01% |
| dev_wide | Development | 771 / 770 | 5 | 1,228,524 | 1,391,568 | 13.27% |
| test_32x3 | Holdout | 256 / 98 | 5 | 365,070 | 380,497 | 4.23% |
| test_64x5 | Holdout | 323 / 322 | 7 | 779,820 | 865,264 | 10.96% |
| test_128x2 | Holdout | 259 / 258 | 4 | 511,771.5 | 539,593 | 5.44% |
| test_512x4 | Holdout | 2,051 / 2,050 | 6 | 2,998,965 | 3,469,514 | 15.69% |

The plot's solid line is equality, not a fitted regression. Its gray region
is [0.8, 1.2] times the FPGA value. Squares identify development cases;
circles identify holdouts. No point has been removed to satisfy the limit.

## Workload And Window

The six cases and their development/holdout split were generated before
measurement in [the input plan](raw/inputs-sorted/plan.json). They are small
synthetic fan-out/lane-chain graphs with different widths and depths, **not
six independent real-world graph families**. The largest has only 2,050
initial edges. The shared topology family limits generalization.

Both sides preload the CPU-converged old-graph distances. An absent cheap
edge `0 -> 1` is inserted, then device propagation runs through convergence,
including the final drain round. These are nonempty propagation cases, not
update-only or zero-change timing. The CPU reference checks the final state.
For every round, FPGA `processed_edges`, `source_requests` and `task_count`
must equal the corresponding simulator counts; equal total time alone is
insufficient.

The common boundary is **maintenance kernel duration plus the sum of the
per-round reader/compute event spans**. Overlapping reader/compute durations
are not double counted. FPGA nanosecond event spans are converted to cycles
using the driver-reported **150 MHz** core clock. Simulator cycle intervals
use the same bounding-span convention. Initial graph/state preparation,
DMA, host launch/wait gaps, inter-round host work and readback are excluded.
This is not Figure 7's resident wall-time boundary or Figure 8's
setup-inclusive update-throughput boundary.

## What Changed And How It Was Estimated

The original model underpredicted these two development windows by roughly
82% and 47%. The hardware image was not changed. A diagnostic host adds only
per-round profiling output and a relocated include;
[the complete patch](diagnostic_host.patch) is included. The production-host
development measurements are also retained in
[board-dev-board0b](raw/board-dev-board0b/results.json), separately from the
diagnostic-host measurements selected in the table.

We estimated an **effective extra reader request-path delay** from only the
first reader event in each development case. Both have 380 modeled reader
requests. `(FPGA reader cycles - original simulated reader cycles) / 380`
gives 102.17 and 94.42 cycles/request. Their mean, rounded to the nearest
10 cycles, fixes one parameter at **100 cycles**. See the exact
[frozen estimates and profile hashes](raw/frozen-reader-transport/freeze.json)
and [frozen profile](raw/frozen-reader-transport/profile.json).

The parameter is applied inside the finite AXI read-address request path,
so delay hiding, queues, backpressure, contention and reader/compute overlap
remain simulated. It is **not a multiplier applied to the final cycle count**.
Reader/maintenance ports are separate from compute ports in the existing
`SpineAxiInterfaceProfile::port_config`. Applying the reader-derived delay
to all ports overpredicted the wide development case by about 78%; that
[failed development hypothesis](raw/sim-transport-development/results.json)
is retained and was never applied to holdouts. The reader-only scope was
fixed before the four holdout predictions and their timing comparison.

This coefficient is calibrated, not independently measured physical AXI or
HBM latency. The estimate can absorb unmodeled control/cache-loader delays
as well as transport delay; these contributions are not identifiable from
the available event counters. The experiment supports **total event-window
accuracy within this small SSSP family**, not the unique physical correctness
of that delay explanation.

The default is zero and the calibration is opt-in through this experiment's
profile. Both development `result.json` objects are exactly identical across
the original plugin and the rebuilt plugin with the override disabled,
including every cycle, correctness field and traffic counter. This does
not retroactively calibrate or replace earlier Figure 9/10/11 results.

Verification also passed all 48 focused experiment, SST-runner and repository
organization tests. Re-pairing archived logs reproduced all six numerical
rows, and the extracted package rendered independently. Raw receipts retain
their original whitespace and line endings rather than being reformatted.

## Limits And Hardware Identity

- This does not establish <=20% error on large real graphs, CC, ResPR,
  FullPR, dense frontiers, carries, deletion fallback or saturated HBM.
- Total-window agreement is not stage calibration. For example, predicted
  maintenance alone is still about 42%/34% below its development FPGA
  durations; other errors can cancel. Do not use this plot to validate the
  ten-stage Figure 10 breakdown.
- The measured image is the existing SSSP split-kernel xclbin, SHA-256
  `2000ded183adffce4880792a3edcefa82eb462c460777fd536602397a77cf5dd`.
  Its source path and actual clocks are recorded in
  [the board receipts](raw/board-holdout/results.json). The inherited base
  simulator profile contains older HLS/image anchors; those anchors must
  **not** be cited as this experiment's measured binary identity. Matching
  the checked work does not prove complete source/architecture equivalence.
- The working device was index 0, BDF `0000:82:00.1`, renderD131. Earlier
  admission/management-timeout attempts are retained under `raw/board-dev*`;
  they are not measurements and no global device reset was performed.
- Board runs used a 16-GiB cgroup, zero swap, an exclusive lease and live
  memory supervision; the plugin build used a 12-GiB limit. Simulator
  subprocesses used a 4-GiB limit, 32-GiB reserve and 120-second timeout.

## Replot And Replay

The zip contains this guide, the PNG/PDF, selected CSV/summary, all small raw
logs and results, inputs, profiles, the changed source files, host source
and patches. Xclbins, executable binaries, toolchains and shared libraries
are indexed by path/hash, not duplicated. `manifest.json` hashes every
included file except itself and the zip.

For plotting only, extract the zip and run its standalone renderer. Python,
Matplotlib, LaTeX `txfonts` and `dvipng` are required. Styling uses the
existing Python/Matplotlib and TX Typewriter convention.

```sh
python3 code/spine_cycle_sim/experiments/evaluation_impact/fpga_cycles/render.py \
  --data data/cycles.csv --output /tmp/fpga-cycle-validation
```

From the matching full repository checkout, independently recompute the
pairing from archived logs without modifying any frozen path or receipt:

```sh
P=/absolute/path/to/extracted/package
M=spine_cycle_sim.experiments.evaluation_impact.fpga_cycles
python3 -m "$M.analysis" \
  --board "$P/raw/board-dev-diagnostic/results.json" "$P/raw/board-holdout/results.json" \
  --simulation "$P/raw/sim-reader-transport-development/results.json" \
               "$P/raw/sim-reader-transport-holdout/results.json" \
  --relocate-root /data/chuxiao/checks/fpga-cycle-validation-20261107 "$P/raw" \
  --output /tmp/fpga-cycle-replay
```

To run new inputs, use `python3 -m "$M.inputs" --output /tmp/new-inputs`.
Build the plugin into a fresh directory with `make -C cpp/sst
BUILD_DIR=/absolute/path/to/new-plugin`, using a bounded build cgroup.
Then run `"$M.simulation"` with `--inputs /tmp/new-inputs/plan.json`,
`--profile "$P/raw/frozen-reader-transport/profile.json"`, `--library
/absolute/path/to/new-plugin`, a fresh `--output`, and `--split holdout`.
The board runner requires an exclusive idle board and the documented finite
cgroup; the archived `command` arrays are the exact commands actually run.
The original diagnostic host compilation command was not saved, so its
source and measured executable hash are provided rather than an invented
build receipt.

## Suggested Caption

Measured FPGA versus simulated device-event cycles for warm dynamic SSSP.
Two development cases estimate one effective reader request-path delay;
four withheld width/depth cases validate the frozen profile. All cases
propagate to convergence and pass CPU-reference and per-round work checks.
The shaded region denotes +/-20% error; maximum holdout absolute error is
15.7%. Results are limited to this small synthetic topology family and
exclude host/DMA overhead.
