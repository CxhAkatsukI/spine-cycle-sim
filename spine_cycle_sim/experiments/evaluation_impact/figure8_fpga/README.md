# One-Pass FPGA Figure 8

This package owns a fresh persistent update-only FPGA measurement. It does not
change the simulator, a frozen prior figure, or the manuscript. Code is separated
into input conversion, bounded board execution, receipt validation, and plotting.
The thin native wrappers live in `cpp/tests/evaluation_impact/figure8_fpga/` and
include pinned production hosts instead of copying their implementations.

## Scope

- Panel a: AU/SU/WK/SO/PK, 4,096 chronological insertions in ten batches.
- Panel b: AU, 131,072 chronological insertions in 10/100/1,000 batches.
- One sample per arm, no warmups or statistical repeats. The initial graph is
  loaded once per arm and stays resident throughout the sequence.
- Count initial native layout and upload plus each batch's preparation, upload,
  kernel launch, and completion wait. Do not run graph algorithm propagation.
- Exclude parsing, FPGA programming, validation/status readback, and logging.
  Validate the completed update sequence before admitting a measured point.
- Both arms receive the same original vertex IDs, weighted graph, trace order,
  and chronological batch boundaries. G uses trace-aware PMA reservation.

`board.py` requires the existing exclusive board lease, finite zero-swap cgroup,
and live memory reserve. The two arms run sequentially; the first arm alternates
between cases. An error is retained, never replaced with a prior simulator row.
`analysis.py` checks every batch count, final correctness status, and timer sum.

## Commands

Run from the repository root. Bind the four absolute host/image paths in a JSON
object with keys `spine_host`, `spine_image`, `gr_host`, and `gr_image`.

```sh
module=spine_cycle_sim.experiments.evaluation_impact.figure8_fpga
python3 -m "$module.inputs" --help
python3 -m "$module.board" --help
python3 -m "$module.sources" --help
python3 -m "$module.delivery" --help
python3 -m "$module.render" --data /path/to/fig8_fpga.csv --output /path/to/figures
python3 -m unittest tests.test_figure8_fpga tests.test_figure8_fpga_sources
```

The November 7 run binds shared G metadata (`--metadata-replicas 1`) consistently
across the matrix and the native Spine L2 bootstrap. These are explicit policies,
not claims of cycle calibration to the older L4 simulator figure. Source/image
identities, exact execution commands, clocks, per-batch raw logs and both timing
components are retained with the delivery, under the existing Figures 7--11
handoff directory.

The eight-pair attempt completed with four valid pairs and four Spine failures.
Its owning handoff is
`docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105/current_fpga/fig8_persistent_once_20261107/`.
Failed pairs are explicit missing timings, not simulator replacements.
