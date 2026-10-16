# Native Multi-Shard G Source Coverage

## Decision

`g-native-geometry-v1` passes all six declared source rows:
`NATIVE_G_SOURCE_PASS_NOT_RTL_OR_BOARD`. The
[portable capsule](evidence/index.json) contains frozen source, runner snapshots,
contracts, raw output, commands and resource logs. Its verification replays
the raw rows without opening the live campaign or toolchain paths.

This closes a **functional source-coverage gap**, not native multi-shard XRT
binding, integrated RTL progress, board timing or original-G performance.
Both cache arms pass; neither is a hardware measurement. ReGraph computation
and host-inclusive performance are outside this check.

## Why This Fixture

The unchanged production builder moves update-dense sources toward the hot
prefix. Small real traces therefore exercise only hot segments even when
the test uses a native 65,536-vertex partition. The earlier
[real host-prepared matrix](../host_prepared/README.md) deliberately discloses
that limitation; it remains unchanged.

This deterministic synthetic graph retains the full 131,072-segment capacity
of each hot half. All 262,148 sources have equal reservation density, making
the production permutation identity; every ID is checked. Sources on both
sides of the actual hot/cold boundary are then selected. No smaller cache,
compressed geometry or direct-memory replacement is used to force a cold hit.

| Property | Declared scope |
| --- | --- |
| Graph | 262,148 vertices; initially 524,296 weighted edges |
| Destination partitions | Five native 65,536-vertex shards; shards 0 and 4 populated, 1--3 empty |
| Initial edges | Each source connects to destination 0 and destination 262,147, both weight 7 |
| Reservation | 1,048,592 future physical operations establish fixed production layout and mapping |
| Executed schedule | Empty batch; delete 20 edges; reinsert those 20 at weight 3 |
| Paired arms | Pristine hot-cache reference and registered cache; production cold DDR in both |
| Updates | 40 executed operations **per arm**, 80 across both arms; not the entire reservation trace |
| Nonempty-batch ports | Hot-even 6, cold-even 4, hot-odd 6, cold-odd 4 |
| Direct handoff | 1,048,598 physical packets per batch across all five shards, including padding/dummies |
| Logical edge counts | 524,296; 524,276; 524,296, checked after each batch |

The exact source IDs are in `native_contract.json` inside the capsule. The
sequence checks persistent PMA buffers without restoring them between batches;
row/binary metadata remain unchanged. All four PMA buffers, live entries,
padding, ordered dispatch and direct bank-streaming adapter outputs are
checked against the independent oracle. The production host layout, runtime
packing and metadata addressing helpers are used unchanged.

The inherited preparation also freezes the earlier seven small real-input
fixtures for dependency provenance. They are **not executed** in this attempt
and do not add seven rows to its six-row native matrix.

## Safety And Costs

The entire supervisor and its children run in one 4-GiB hard/3-GiB high
cgroup, with zero swap, group OOM kill, CPUs 126--127 and a 65-minute lifetime.
Compilation has a 300-second deadline and execution an 1,800-second deadline.
Atomic admission reserves the complete finite budgets of live peers, this
4-GiB job and 32 GiB headroom. R and A4 were still running when the job was
admitted: no blanket wait for other FPGA tools was imposed.

Compilation took 8.54 s; execution took 42.27 s. Sampled peak process-tree RSS
was about 518 MiB and 656 MiB respectively. All cgroup memory events were
zero. These numbers are **CPU verification costs**, not FPGA cycles or update
throughput. The production-plan allocation was 140,673,024 bytes.

External search/dispatch/output queues are bounded in this source harness.
Internal cache/DDR C-simulation queues remain unbounded, so source success
does not establish integrated RTL backpressure or progress.

## Review And Reproduce

Code owners are
`cpp/tests/evaluation_impact/common_g/complete_pipeline/native_geometry/`
and
`spine_cycle_sim/experiments/evaluation_impact/common_g/complete_pipeline/native_geometry/`.
Fixture construction, execution, validation, preparation and delivery have
separate modules. Existing route/source evidence and HLS were not edited.

From the repository root, verify the delivered capsule:

```bash
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.native_geometry.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/native_geometry/evidence"))'
python3 -m unittest discover -s tests -p 'test_g_native_geometry*.py'
```

The fresh-run CLI is
`python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.native_geometry.study`.
It requires a new `--output`, pristine GraSU `--upstream`, production
`--integration`, vendor `--hls-include` and the exact bounded cgroup above.
Do not execute it uncontained. The full compiler command, include dependencies
and original paths are indexed in `results.json` inside the capsule; external
compilers/system headers and the executed binary are indexed, not bundled.

Raw attempt:
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-native-geometry-v1`.

**Still open:** native multi-shard/cold board-host bindings, metadata refresh
on actual hardware, integrated resource/timing closure, original-G performance,
matched adapter/R measurements and the complete Spine comparison.
