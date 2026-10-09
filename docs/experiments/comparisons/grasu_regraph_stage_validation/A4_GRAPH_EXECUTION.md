# A4 Whole-Graph Execution Checkpoint

Status: `A4_FULL_GRAPH_FUNCTIONAL_PASS_TIMING_PREDICTED`. The independent
four-Little/zero-Big path now runs all original scheduled partitions through
acknowledged PR writeback on full Amazon and two neighboring inputs. Model
cycles are predictions under an explicit mock-memory contract, not FPGA
measurements, publication-speed matches or matched adapter-overhead results.

## Fixed Results

The [execution contract](../../../../configs/experiments/original_regraph_a4_execution_v1.json)
declares eight cases and two runs per case. The
[implementation contract](../../../implementation/grasu_regraph/original_regraph_a4_execution.md)
defines task progress, the resident one-iteration window and resource limits.
Regenerated author-host and Gather/Apply captures are accepted only when their
source matrix and numerical identities match the frozen references. Report
paths, resource timings and revision metadata may differ; matching a particular
machine's absolute-path report hash is not required.

| Case | Nonempty partitions | State parent credits | Memory latency | Cycles |
| --- | ---: | ---: | ---: | ---: |
| Boundary ring | 3 | 16 | 64 | 113,714 |
| Boundary ring, reverse registration | 3 | 16 | 64 | 113,714 |
| Boundary ring, two state parents | 3 | 2 | 64 | 437,317 |
| Boundary ring, latency 128 | 3 | 16 | 128 | 118,247 |
| Skewed sources | 1 | 16 | 64 | 35,506 |
| Skewed sources, reverse registration | 1 | 16 | 64 | 35,506 |
| Complete Amazon | 12 | 16 | 64 | 886,840 |
| Complete Amazon, reverse registration | 12 | 16 | 64 | 886,840 |

Every first/repeat pair and reverse-registration pair has identical complete
state captures, cycles, per-path lifecycle records and ledgers. UBSan separately
checks the boundary, skewed and full Amazon inputs, reproducing the same
results without diagnostics. Six damaged controls are rejected: descriptor
header, kernel assignment, invalid source, signed arithmetic overflow,
changed edge value and truncated degree capture. Changed-edge rejection checks
the full pre-Apply oracle, not just rounded final PR properties.

Complete Amazon uses 735,324 original vertices and 5,158,388 logical edges;
original padding produces 5,165,928 physical edges. It checks 786,432 pre-Apply
sum words and 3,145,728 output-replica words, including padded extents.

| Amazon memory ledger | Bytes |
| --- | ---: |
| Compact scheduled edges | 41,327,424 |
| Source properties, including requested lookahead windows | 37,257,216 |
| Degrees | 3,145,728 |
| Total reads | 81,730,368 |
| Acknowledged writes, all four replicas | 12,582,912 |

Requests, physical/logical edges, dummy updates, per-partition terminators,
degree responses, writer acknowledgements and every registered queue drain
consistently. Amazon records 44 next-task starts before the preceding
partition's publication completes. There is no added global publication
barrier. State ports reach nine outstanding bursts under ordinary input rate;
the two-parent control preserves state but materially increases elapsed
cycles. This demonstrates why parent and burst capacities cannot be conflated.

All ten CTest executables pass in the new isolated Release build. Four legacy
component outputs remain byte-identical to their pre-edit executable outputs;
old/new full Gather and Apply source-comparison outputs also match, covering
786,432 and 393,216 original-source words respectively. Optional AXI parent
arguments preserve the old default of two. Frozen component results are not
rewritten with the new whole-path timing configuration.

All 120 focused Python tests pass. All 2,437 protected files and the frozen
SST plugin keep their hashes; no production numerical body changes.

The 37 bounded steps total 148.48 seconds. The two-job Release build takes
68.69 seconds with maximum process RSS 690,716 KiB. Amazon Release runs take
about 5.9 seconds with peak RSS about 173 MiB; UBSan takes 15.94 seconds and
about 175 MiB. These are CPU execution/resource measurements, separate from
modeled device cycles. Runs remain within 4-GiB address-space limits and a
16-GiB host memory reserve; graph cases execute sequentially.

## Evidence And Reproduction

- [Full results](a4_results.json): all declared cases, raw commands/resources,
  source/input/binary identities, original HLS interface evidence and ledgers.
- [Verification index](a4_verification.json): raw-archive and result hashes,
  independently rechecked inputs/captures and numerical gates.
- [Preservation record](a4_preservation.json): protected files/plugin and old
  numerical bodies unchanged, focused tests and regression references.
- `raw_a4_graph_execution.tar.gz`: final logs, reports and metadata, plus
  preserved preflight and unsuccessful evidence-collection attempt. Large
  graph/state captures, author source trees and binaries are not redistributed.
- [AXI evidence index](a4_axi_verification.json) and
  `raw_a4_axi_instances.tar.gz`: three generated HLS top-level modules and two
  frozen scheduling reports, allowing interface checks in a fresh workspace.
  Generic Xilinx AXI IP bodies and routed hardware are not included.

The main 562-file archive is 377,897 bytes, SHA-256
`482233408f0461b9ca177f810601745c51025bf842ac03f1202ba0260e0f1185`.
The five-file AXI archive is 156,821 bytes, SHA-256
`5d9dec73bfa09a2d0b7a74e4e0ee2883af159f0bc6b2baba6b3b2cb365b19d30`.

Use the [source pins](README.md) and
[author-input reproduction](ORIGINAL_HOST_INPUTS.md) first. On a fresh workspace,
restore the frozen [original HLS interface evidence](HLS_SCHEDULES.md) below;
the runner checks actual instance overrides, not generic AXI template defaults.
The complete HLS scheduling campaign remains separately reproducible. Do not
overwrite existing evidence when restoring this small archive:

```bash
mkdir -p results/upstream_stage_controls
tar --keep-old-files -xzf docs/experiments/comparisons/grasu_regraph_stage_validation/raw_a4_axi_instances.tar.gz -C results/upstream_stage_controls
```

Reproduce original Gather and
Apply captures using the first and third source-control commands in
[the state checkpoint](LITTLE_STATE_MODEL.md#reproduce). Build the predecessor revision
in a separate worktree when recreating the pre-edit baseline:

```bash
git worktree add --detach build/a4-legacy-source 2dc0843
cmake -S build/a4-legacy-source -B build/a4-legacy -DCMAKE_BUILD_TYPE=Release
cmake --build build/a4-legacy -j2
```

Capture its four default component outputs using the shared bounded runner:

```python
from pathlib import Path
from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded

root = Path.cwd()
old_source, old_build = root / "build/a4-legacy-source", root / "build/a4-legacy/cpp"
baseline = root / "results/upstream_stage_controls/reproduce_a4_baseline"
baseline.mkdir(parents=True, exist_ok=False)
targets = ["gather_tests", "frontend_tests", "state_tests", "iteration_tests"]
files = [old_source / "cpp/CMakeLists.txt", old_source / "cpp/tests/original_regraph/memory_fixture.hpp"]
files += sorted((old_source / "cpp/include/spine_sim/original_regraph").rglob("*.hpp"))
files += sorted((old_source / "cpp/src/original_regraph").glob("*.cpp"))
record = {"source_files": [{"path": str(p.relative_to(old_source)), "sha256": sha256_file(p)} for p in files]}
record["runs"] = [{"target": target, **run_bounded([str(old_build / ("original_regraph_" + target))],
    root, baseline / target, timeout=60, memory_gib=4, reserve_gib=16)} for target in targets]
assert all(row["exit_code"] == 0 and not row["timed_out"] for row in record["runs"])
atomic_write_json(baseline / "baseline.json", record)
```

Then run the fixed matrix using fresh output paths:

```bash
python3 scripts/run_original_regraph_a4.py \
  --inputs results/upstream_stage_controls/reproduce_original_host_inputs \
  --baseline results/upstream_stage_controls/reproduce_a4_baseline \
  --gather-captures results/upstream_stage_controls/reproduce_state_gather \
  --apply-captures results/upstream_stage_controls/reproduce_state_apply \
  --out results/upstream_stage_controls/reproduce_a4_execution
python3 -m unittest discover -s tests -p test_original_regraph_execution.py
```

`original_regraph_execution.delivery.deliver(root, run, destination, attempts)`
rechecks raw evidence and refuses to overwrite its three outputs. Whole-state
captures and copied author inputs are indexed for regeneration. Compilation,
execution, input admission, analysis, negative controls, instrumentation and
packaging have separate named owners behind one thin CLI.

The first matrix's numerical runs and UBSan cases passed, but dependency
collection rejected its noncanonical GCC target name. The final run uses
`-MT probe`, includes the complete damage/delivery gates, and passes source
identity checks. The earlier attempt is retained rather than relabeled.
The additional final reproduction regenerates all three source-input families
under fresh paths before the full matrix; it checks the relocation/reproduction
gate in actual execution instead of relying only on mocked unit tests.
All eight complete numerical results remain identical to the earlier final-v2
matrix. Final-v3 is the authoritative report delivered here.

## What Remains

Original Big/mixed whole-graph execution is not implemented here. The original
graph-selected topology, publication event window/clock and realistic memory
timing still need admission before any approximately ten-percent publication
match. Standalone original G timing and its paper/source geometry controls
remain open. A4's downstream resource contract must be held fixed when adding
the PMA adapter B; then quantify input work, overlap and elapsed overhead.
Host/C composition follows the independent stage gates. A close complete-system
total cannot substitute for them.
