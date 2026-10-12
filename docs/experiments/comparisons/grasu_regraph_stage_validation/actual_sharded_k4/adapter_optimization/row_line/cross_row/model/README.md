# Cross-Row Model Checkpoint

## Decision

The default-off production-adapter model now represents the synthesized V3
cross-row reader and finite publisher as separately owned components. Five
legacy SST cases remain identical in every result field. All 27 core test
executables pass, including 210 cross-row packet/pressure/restart scenarios.
All six resident AU/SU/WK runs preserve full external state, work, rounds and
traffic. **This is functional and traffic admission, not FPGA timing
calibration, an original-A4 match, or completion of the overall study.**

The final Python regression adds six portable-delivery checks to the frozen
checkpoint: 363 sharded-K4, 120 original-ReGraph and 15 repository-structure
tests pass. Their transcripts, resource records and test source are sealed
separately in [raw_regression.tar.gz](raw_regression.tar.gz), indexed by
[regression.json](regression.json); the earlier checkpoint is not rewritten.

The reference here already has whole-line directory reads, row prefetch and
stop-after-last. It is not the historical routed adapter or original A4.
The candidate changes reader/publisher scheduling, not the graph, PMA layout,
arithmetic, downstream resources or timing multiplier.

## Reading And Code

| Item | Location |
| --- | --- |
| Full legacy/core/24-row timing report | [evidence/results.json](evidence/results.json) |
| Portable checkpoint, identities and failed attempts | [evidence/raw_checkpoint.tar.gz](evidence/raw_checkpoint.tar.gz), [verification.json](evidence/verification.json) |
| Complete six-run resident report | [resident_evidence/results.json](resident_evidence/results.json) |
| Resident inputs, full outputs, source and isolated plugin | [resident_evidence/raw_model.tar.gz](resident_evidence/raw_model.tar.gz), [verification.json](resident_evidence/verification.json) |
| Production HLS and complete RTL evidence | [Parent HLS guide](../README.md) |
| Model contract | `configs/architectures/grasu_regraph_cross_row_sssp_compute_v1.json` |
| Reader, publisher and invocation control | `cpp/src/regraph_pma_cross_row/{reader,publisher,control}.cpp`, private `state.hpp` |
| Shared adapter interface and default-off dispatch | `cpp/include/spine_sim/regraph_pma_adapter.hpp`, `cpp/src/regraph_pma_adapter.cpp` |
| Profile admission and portable evidence owners | `spine_cycle_sim/experiments/sharded_k4_stages/row_line/cross_row/model_*.py` |
| Shared bounded runner, validation and safe archive extraction | `spine_cycle_sim/experiments/sharded_k4_stages/row_line/model_*.py` |
| Packet/pressure and logical RTL-shape tests | `cpp/tests/routed_regraph/adapter_tests.cpp`, `adapter_timing_matrix.hpp` |
| Profile, conservation, packaging and tamper tests | `tests/test_sharded_k4_cross_row_model*.py`, `test_sharded_k4_model_archive.py` |

Both build lists include the new numerical owner. The default SST plugin and
all earlier bitstreams/packages remain unchanged. This checkpoint uses an
isolated plugin with SHA-256
`19bab64b9ee0ec09f04686d8e8f9cf99254558bb052b54650c836b312749751d`.
The profile pins the V3 HLS XO
`7d1785677ca7b54861688d7670d813ca2a4cfdc1e2c83cbc53151cd03ad02b6b`
and the dedicated-source-reader basis; it does not silently substitute the
later pairwise source-reader topology.

## Resident Results

| Fixture | Vertices | Destination partitions | Rounds | Whole-line cycles | Cross-row cycles | Reference/candidate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AU | 515,281 | 8 | 2 | 15,063,595 | 5,777,668 | 2.607x |
| SU | 567,316 | 9 | 2 | 24,516,942 | 9,879,419 | 2.482x |
| WK | 1,140,149 | 18 | 1 | 8,621,421 | 2,625,590 | 3.284x |

These are **predicted resident-compute cycles**, not FPGA speedups. The
window excludes updates, initial migration, host launch/wait and inter-round
host gaps. Complete states equal the preserved previously checked FPGA
fixture oracle, not a newly generated independent Dijkstra oracle. Logical
edges per round are 390,855 / 616,126 / 1,142,360; source IDs and reserved
PMA slots are retained. Both arms issue exactly 158,560 / 243,884 / 45,883
directory requests over their complete runs. Thus the modeled improvement
comes from overlap, not omitted directory traffic or free preprocessing.

The six runs took 85.13 seconds in total, with maximum sampled process-tree
RSS 604.88 MiB and minimum available memory 43.03 GiB. Each child had a
180-second timeout, 3-GiB tree budget, 16-GiB live reserve, and affinity
112--113; runs were serial. The legacy matrix includes warm multipart SSSP,
mixed cold SSSP, CC, warm residual PR and residual update-only. Its five
result files remain byte-identical; that does not calibrate the new model
for the other algorithms.

## Timing Diagnostic And Limits

All twelve production-RTL shapes are checked for both arms, without fitting
parameters. Packet data/order and physical traffic agree in all 24 rows.
For the cross-row candidate the eleven nonempty rows have 2.50--9.02% cycle
error. The empty call is 2 predicted versus 6 RTL cycles (66.67% error).
The whole-line reference also fails the empty and downstream-stall timing
checks; its stalled row is 1,648 predicted versus 2,416 RTL cycles (31.79%).
These failures remain in the report and prevent an all-row calibration claim.

The model explicitly bounds the loaded FIFO at 16 entries, in-flight segment
descriptors at 74 and shared AXI pending reads at 16. Directory lines cache
eight entries; wholly empty blocks bypass the inner pipeline. This preserves
finite backpressure and overlaps occupied rows within a directory block.
Contiguous 16-slot-aligned intervals are required; general historical
unaligned HLS intervals are not admitted by this model.

The 71-cycle minimum read-to-use latency is inherited, not measured here.
Reader loop depth 74 and publisher half-loop depth 2 come from synthesis,
but their use as nominal drain/startup costs is not a complete extraction of
RTL control timing. The C++ invocation boundary, MockMemory/FixedAxiPort and
depth-32 output FIFO differ from the RTL start/done, ordered AXI responder
and direct sink. No physical HBM banks, refresh, routed interconnect or
actual ReGraph sink participate in that diagnostic. V3 remains unrouted;
its approximately doubled adapter LUT estimate is not resource-free.

## Reproduce

Run from the simulator worktree. Portable rechecks need neither proprietary
tools nor the original external experiment directories:

```bash
D=docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/cross_row/model
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.model_checkpoint --destination "$D/evidence" --verify-only
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.model_delivery --destination "$D/resident_evidence" --verify-only
python3 -m unittest discover -s tests -p 'test_sharded_k4_cross_row_model*.py'
```

The archives contain exact frozen sources, profiles, plugin, build flags,
inputs, outputs, test transcripts and resource records. Extract into a fresh
directory; never rebuild over that plugin. Core reproduction uses a separate
Release CMake build and both applicable source lists. SST replay uses a fresh
plugin built with `cpp/sst/Makefile` and the pinned HBM configuration. The
resident study CLI is:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.model_study \
  --plugin /absolute/path/to/fresh/plugin \
  --scope resident_matrix_v1 \
  --fixture /absolute/path/to/au --fixture /absolute/path/to/su --fixture /absolute/path/to/wk \
  --output /absolute/path/to/fresh-run
```

Use the three archived `resident.bin` files and preserved expected values;
the runner requires the entire pinned matrix and refuses an existing output.
The first failed default-plugin baseline and the first build failure are
retained, not counted as accepted runs. Failed raw attempts must not be used
as passing baselines.

## Remaining Gates

1. Check the cross-row actual adapter+modified K4 against original A4 under
   the same logical state and round, retaining the existing negative controls.
   List port/state-copy differences rather than calling four frontends a
   strict resource match. This comparison is not yet in this checkpoint.
2. Route and measure V3 when the unchanged 40-GiB job plus 16-GiB reserve can
   be admitted. Preserve old/new board results; do not substitute model
   ratios for FPGA speedups.
3. Resolve endpoint/memory differences before any stronger timing claim.
   Publication reproduction and full update-to-convergence comparison remain
   separate from local structural or one-round diagnostic evidence.

The paper and figure packages are not modified by this delivery.
