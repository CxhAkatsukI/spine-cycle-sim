# Three-Algorithm Figure Data

This package extends the preceding SSSP-only Figure 9 study. It does not edit
the paper, rebuild FPGA kernels, or admit original-publication performance.

## Review Order

| Owner | Responsibility |
| --- | --- |
| `core_gates.py` | Fresh frozen Release build, focused PR gate and complete core regression |
| `matrix.py` | AU/SU/WK, eight user mutations, directed SSSP, reciprocal CC and sink-free PR projections |
| `study.py`, `sst_config.py` | Frozen sources, bounded fresh SST harness, per-arm execution and saved failures |
| `regression.py`, `sssp_replay.py` | Twelve SSSP trajectories; strict exact gate by default, explicit read-credit correction mode |
| `validation.py` | Complete pair selection, raw/configuration/state checks, core gates and all-channel energy |
| `tables.py`, `delivery.py` | Derived CSVs and a portable, hash-checked evidence extension |
| `source_snapshots.py` | Explicitly index the redundant full-repository snapshot while archiving and verifying its corresponding code-only snapshot |

The C++ harness has separate input/oracle, finite resident G/R composition,
Spine execution, a thin existing-SSSP path and SST wiring owners under
`cpp/tests/evaluation_impact/figure_refresh/multialgorithm/`.
The new production-core PageRank preparation module owns finite state/degree
reads, acknowledged degree updates and replicated source publication. Its
sixteen-lane/eight-bank FP32 dangling reduction follows the existing HLS;
both preparation and split-state Apply charge 128 final reduction cycles.

## Run

Use a new Release CMake directory with tests enabled. Run all 39 core tests,
including the independent CC and warm-PR oracle gates. Do not overwrite a
frozen core. Saved commands and resource records accompany each attempt.
The `core_gates --output OUT` command freezes the sources and performs these
checks under the same finite memory reservation; invoke it in the cgroup
shown below, with a separate unit and fresh output directory.
Then run the study from the repository root, replacing `OUT`, `CORE` and CPU
with a fresh output path, that verified core directory and an allowed CPU:

```bash
systemd-run --user --wait --pipe --collect --unit=fig9-multi \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 \
  -p OOMPolicy=kill -p RuntimeMaxSec=21600 \
  --working-directory="$PWD" /usr/bin/python3 -m \
  spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.study \
  --output OUT --core CORE --cpu 7 --timeout 1800
```

The runner atomically reserves the entire finite budget, preserves a 24-GiB
live reserve and bounds each child to 4 GiB. Six smoke arms must pass before
the eighteen real-input arms run. Device completion, independent final-state
checks and physical request/beat closure are mandatory; timeouts are retained,
never replaced with projected values. `--smoke-only` selects only the six
small correctness fixtures.

Run `regression --help` for the twelve-case SSSP replay. Run `delivery --help`
for packaging and `delivery --output PATH --verify` for offline verification.
`delivery --publish-from UNSPLIT --output FRESH` reuses the existing 64-MiB
archive transport, preserves the unsplit source, and verifies the published
parts. Both forms retain the same complete-archive hash and numerical evidence.
The delivery is a new subdirectory beside the preceding frozen figure data.
All nine Figure 9 pairs are fresh; no old SSSP energy is reused. The preceding
package remains unchanged and is nested only as historical evidence.
The delivered [results and test report](../../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure_refresh/multialgorithm/README.md)
retain the PR counterexample and distinguish passing core gates from the
non-green full Python suite.

The finite AXI repair reserves a reorder slot before issuing a streamed read
beat. An adversarial backend checks delayed early responses, held consumers,
capacities 1/2/4/32, issue widths 1/4 and both registration/scheduling orders.
This fixes a real deadlock without enlarging the 32-beat production storage.
It can change R cycles, so `regression --allow-read-credit-correction` admits
only an explicit R-cycle delta: complete input/state/byte identities, G cycles
and all Spine outputs must remain exact, and both R registration orders must
agree. The failed strict exact-cycle replay is retained, not relabeled.

## Limits

- Both arms start with the identical old converged state and include the
  accepted insertion batch through new convergence. This is resident device
  work, not host-inclusive E2E time or a new Figure 8 result.
- Spine PR uses the existing oracle-directed, timed correction-work replay.
  Its correction requests are charged, but their functional seeds are not
  derived from AXI responses. This is not production-HLS equivalence.
- Latest R has finite, explicitly selected resources, not a strict original-A4
  resource match. Original CC and warm FP32 residual-PR controls have not been
  admitted; SSSP timing agreement cannot establish their performance parity.
- Original-G performance remains unadmitted. This extension is a simulator
  diagnostic comparison, not a validated original G+R publication baseline.
- HBM energy sums all 32 DRAMSim3 channels, including background and refresh.
  It depends on the modeled device window and is not measured FPGA/ASIC power.
