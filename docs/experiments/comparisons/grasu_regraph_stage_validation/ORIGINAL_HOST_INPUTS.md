# Original Host Input Checkpoint

Status: `ORIGINAL_HOST_LAYOUT_PASS_NOT_DEVICE_TIMING`. Complete original-host
input preparation passes on the full pinned Amazon graph and two neighboring
synthetic inputs for both four Little/zero Big and the artifact's eleven
Little/three Big example. Device cycles and publication-rate errors remain
null. This does not complete original R, G timing or the matched A4/B study.
The subsequent [A4 execution checkpoint](A4_GRAPH_EXECUTION.md) now consumes
these inputs through complete multi-partition PR writeback; its timing remains
predicted rather than a publication-speed match.

## Scope And Results

The [fixed contract](../../../../configs/experiments/original_regraph_inputs_v1.json)
pins seed 73, source revisions, graph identities and all six combinations.
It executes the author's loader, DBG, partition/schedule and PR initialization,
not our port's host preparation. The
[implementation contract](../../../implementation/grasu_regraph/original_regraph_inputs.md)
explains compatibility measures, binary captures and admission boundaries.

| Input | Vertices | Logical edges | Purpose |
| --- | ---: | ---: | --- |
| Boundary ring | 131,073 | 131,137 | Three destination partitions, duplicates and an almost-empty final partition |
| Skewed sources | 65,537 | 8,193 | Sparse source IDs, one nonempty destination partition and empty scheduled lanes |
| Amazon artifact | 735,324 | 5,158,388 | Complete real input, twelve destination partitions; no truncation or ID compaction before original DBG |

Amazon input SHA-256:
`60b383901873b49883d0c67d8b524244ada1977719d25c834014b75238f3a815`.
Its minimum observed ID is one; the original loader retains isolated ID zero
through the `max_id + 1` convention. The publication's graph-selected best
pipeline configuration and throughput event boundary remain separate admission
questions. The artifact's 11+3 example is not silently treated as that best
configuration.

| Topology / input | Dense partitions | Sparse groups | Scheduled tasks | Physical edges | Dummy edges |
| --- | ---: | ---: | ---: | ---: | ---: |
| A4 / boundary ring | 3 | 0 | 12 | 131,336 | 199 |
| A4 / skewed sources | 1 | 0 | 4 | 8,224 | 31 |
| A4 / Amazon | 12 | 0 | 48 | 5,165,928 | 7,540 |
| 11+3 example / boundary ring | 1 | 1 | 14 | 131,312 | 175 |
| 11+3 example / skewed sources | 1 | 0 | 11 | 8,224 | 31 |
| 11+3 example / Amazon | 1 | 2 | 17 | 5,165,928 | 7,540 |

All cases pass full original-to-DBG edge checks, scheduled logical-edge
multiset conservation, original PR initialization and initial signed-arithmetic
domain checks, source lookahead and HBM-capacity checks. Every one of the seven
binary capture files is byte-identical between first/repeat runs and an
independent UBSan build. UBSan emits no runtime diagnostics. The C++ oracle
checks values and edges; the Python analysis checks descriptors, extents and
hashes. It does not infer functional correctness from file size alone.

The final 22 bounded compile/run steps total 41.51 seconds, with maximum process
RSS 478,108 KiB (about 467 MiB). Complete Amazon A4 first/repeat runs take about
3.96 seconds each and use about 431 MiB. These are CPU validation-plus-capture
measurements, not device latency or published preprocessing measurements.
Each child is bounded to 2 GiB with a 16-GiB host reserve and a timeout;
the six input cases run sequentially.

The unchanged previous core build passes all ten CTest executables, including
Spine/GraSU and original-R component tests. All 106 focused Python tests pass;
all 2,437 protected files and the frozen SST plugin keep their hashes. The
accepted SST extraction matrix and
earlier component source comparisons are retained; no new FPGA run, full
Python suite or SST numerical matrix is claimed for input preparation.

## Deliverables And Reproduction

- [Input results](input_results.json): complete matrix, source/dependency/input
  identities, capture hashes, commands, repetitions and resource logs.
- [Verification index](input_verification.json): rechecked raw-file and archive
  identities; large `u32le` captures are indexed rather than copied into Git.
- [Preservation record](input_preservation.json): protected files and frozen
  plugin unchanged, plus current regression results.
- `raw_original_host_inputs.tar.gz`: final report, descriptors, compile/run
  logs, resource records and retained earlier attempts. No author source
  tree, compiled binary or large graph/capture is redistributed.

The 255-file raw archive is 267,259 bytes, SHA-256
`c12320d2efb63e12e0d8548165e43f4d1cfda53be12125d604691e036bb272bc`.

From the repository root, prepare the [pinned sources](README.md), install
real OpenCL/XRT headers and library, and use a fresh output directory:

```bash
python3 scripts/run_original_regraph_inputs.py \
  --xrt-include /opt/xilinx/xrt/include \
  --out results/upstream_stage_controls/reproduce_original_host_inputs
python3 -m unittest discover -s tests -p test_original_regraph_inputs.py
```

Reproduce packaging in a fresh destination; the delivery gate refuses to
overwrite any of its three evidence outputs:

```python
from pathlib import Path
from spine_cycle_sim.experiments.original_regraph_inputs.delivery import deliver

root = Path.cwd()
deliver(root, root / "results/upstream_stage_controls/reproduce_original_host_inputs",
        root / "results/upstream_stage_controls/reproduce_input_delivery", attempts=[])
```

The delivery gate rechecks the canonical contract, complete topology/input/case
order, no duplicate steps, source/header/binary identities, all raw numerical
metadata/capture hashes, repetitions and UBSan evidence. Missing topology or
instrumentation cannot skip verification. Earlier preflights and final-v2
outputs are retained; final-v3 adds instrumented dependency identities and
stronger delivery gates without changing the author algorithms.

## Remaining Stage Work

The next original-A4 gate consumes these scheduled tasks across all partitions,
with explicit per-port AXI parent/burst credits and complete resident PR
writeback. Preserve existing component defaults/results while introducing this
whole-path configuration. Big/mixed execution, graph-selected publication
topology/clock/window admission and standalone original G timing remain open.
Only an admitted A4 path can become the downstream resource reference for B;
then compare PMA-adapter extra work and overlapping elapsed time. Host/C
composition follows those independent stage checks. Similar full-system totals
are not acceptance of any of these missing stages.
