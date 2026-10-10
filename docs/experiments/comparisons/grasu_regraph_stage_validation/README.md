# Isolated G / R Validation

Start with the [delivery conclusions and remaining blockers](CONCLUSIONS.md).
For reproduction, read the [execution and acceptance plan](PLAN.md), then the preceding
[source/comparability audit](../grasu_regraph_publication_match/README.md).
This folder owns the new study's results and conclusions, rather than
scattering them among figure-refresh and daily investigation directories.

## Current Status

SST/Spine extraction passed exact regression in `51565fc`. Independent G/R
controls below are not changes to the frozen paper model, FPGA measurements,
or successful publication-speed matches. Timing prediction, functional
agreement and published-rate reproduction have separate acceptance gates.

| Path | Current evidence | Still required |
| --- | --- | --- |
| G | Eight prepared-PMA and eight guarded host-prepared source16 cases pass; twelve original DDR RTL controls pass; complete finite composition passes twelve configurations; full AU/SU/WK counts repeat exactly and identify a common exploratory Table 4 numerator | Actual temporal converter/operations and original aggregation rule, paper8 geometry, cache/search/controller timing and publication rate admission; unchanged original host is not admitted |
| A | Complete 11+3 graph execution, indexed state and finite ledgers pass under declared tail padding | Original-host allocation compatibility, graph-selected topology, publication memory/clock/window/denominator admission and timing match |
| A4 | Complete Amazon and two fixtures pass every pre-Apply sum, four state replicas and finite ledgers; eight legacy and matched-input-credit controls remain exact | Realistic memory/timing admission and publication comparison |
| B | Eight complete finite PMA+A4 executions pass matched state/work/window/overlap gates; source fixtures prove cold/stale routing; modeled overhead is reported separately | FPGA/RTL timing admission, actual routed-K4 placement, original-G-produced inputs and publication comparison; predicted cycles are not measured overhead |
| C | Not executed | Separate validated G/B windows, measured host orchestration and overlap accounting |

## Review Guide

| Question | Evidence |
| --- | --- |
| What is the plan and what counts as a match? | [Execution gates](PLAN.md), [source/comparability audit](../grasu_regraph_publication_match/README.md) |
| Do complete temporal inputs explain the publication denominator, and are the G/R timers comparable? | [Full AU/SU/WK counts, post-hoc arithmetic clue and event boundaries](PUBLICATION_WORKLOADS.md) |
| Does an older public version recover the missing paper configuration or converter? | [Complete reachable history, deleted GraSU ZIP and ReGraph AE/Release comparison](PUBLICATION_HISTORY.md) |
| Does the prepared original G kernel path agree? | [G source-path control](GRASU_SOURCE_PATH.md) |
| Does trace-aware G host preparation compose with the original kernels? | [G host inputs, bounds failures and compatibility control](GRASU_HOST_INPUTS.md) |
| Do original DDR RTL ports safely alias physical memory under finite pressure? | [Twelve source/RTL state controls, bus tests and event ordering](GRASU_DDR_RTL.md) |
| Does the complete G path preserve source state and requests under shared-bank pressure? | [Finite source16 composition, complete matrix and explicit timing boundary](FINITE_GRASU.md) |
| What do source controls and HLS schedules establish? | [Initial source controls](SOURCE_CONTROLS.md), [HLS scheduling](HLS_SCHEDULES.md) |
| How were complete graph inputs prepared? | [Original host inputs](ORIGINAL_HOST_INPUTS.md) |
| Does complete original A4 work? | [Whole-A4 execution](A4_GRAPH_EXECUTION.md) |
| Does the existing adapter preserve original A4 logical work? | [Adapter source and exact wiring regression](ADAPTER_SOURCE.md) |
| What changes when finite PMA input feeds the same original A4 downstream? | [Matched finite A4/B state, traffic, overlap and predicted overhead](FINITE_PMA_R.md) |
| Does the artifact's 11+3 example work? | [Mixed execution and allocation finding](MIXED_GRAPH_EXECUTION.md) |
| Which Little components were checked separately? | [Gather](LITTLE_FINITE_MODEL.md), [frontend](LITTLE_FRONTEND_MODEL.md), [state](LITTLE_STATE_MODEL.md) |
| Which Big components were checked separately? | [Routing/Gather](BIG_ROUTING_GATHER.md), [memory/Scatter](BIG_MEMORY_FRONTEND.md) |

Component reports retain their checkpoint-specific scope. They are not the
current complete-system status; use the table above for that. Original R's
11+3 example uses declared publication-tail padding and mock memory, not the
unknown graph-selected best topology or admitted U280 paper timing.

[Independent upstream source pins](source_pins.json) record fresh clean
checkouts and inspected file hashes. They are distinct from the modified local
HLS ports. Reproduce them under ignored build output:

```bash
git clone https://github.com/Xtra-Computing/ReGraph.git build/publication_sources/regraph
git -C build/publication_sources/regraph checkout --detach 365456826cef495285383d939907f847e05ad74b
git clone https://github.com/qgwang-hust/GraSU.git build/publication_sources/grasu
git -C build/publication_sources/grasu checkout --detach e95da256be9e7f2361449323b6fe0abf98c1b152
```

The GraSU geometry question recorded in the source-pin snapshot is now
resolved: Section 6.1 explicitly specifies eight 4-byte entries, a 32-byte
PE buffer. Current upstream instead packs sixteen 32-bit entries, a 64-byte
segment. Host-side 64-bit edge records are converted into 32-bit destination
slots before device upload; they do not explain away this difference. See
[the source-control findings](SOURCE_CONTROLS.md). The passing control uses
the unmodified source's 16-slot geometry. A separate, explicitly named
paper-8-slot control is required before a paper-configuration timing claim;
the source configuration is not assumed to have equal performance.

The upstream ReGraph repository includes an AM candidate at
`dataset/amazon-2008.mtx`: 5,158,388 two-column edge rows, SHA-256
`60b383901873b49883d0c67d8b524244ada1977719d25c834014b75238f3a815`.
Despite the extension, it is not a Matrix Market file with a header. The
upstream loader keeps the integer IDs and uses maximum ID plus one. This
candidate passes original-host DBG/partition/task and initial-state admission,
complete A4/mixed resident-iteration controls, and the declared finite PMA/A4
comparison. Publication-event and timing admission remain open; its availability
does not make Table IV's graph-selected topology known.

## Reproduce Source Controls

Use a fresh output path; the runner refuses to overwrite previous runs:

```bash
python3 scripts/run_upstream_stage_controls.py \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --out results/upstream_stage_controls/reproduce_source_functional
python3 -m unittest discover -s tests -p test_upstream_stage_controls.py
```

The source generator uses Python 3.11, pinned in the contract. The study
runner itself also runs on Python 3.13. HLS headers and GMP are needed only
for these optional author-source controls; the ordinary C++ core still builds
without Vitis. Processes run sequentially with a 2-GiB address-space limit,
128-MiB stack allowance, 16-GiB memory reserve, and bounded compile/run times.

The [v2 contract](../../../../configs/experiments/grasu_regraph_upstream_controls_v2.json)
adds the Big source control to the preserved first Little/cache matrix. Code
ownership is in
[upstream_controls](../../../../spine_cycle_sim/experiments/upstream_controls/)
and [source probes](../../../../cpp/tests/publication_sources/). Source
preparation, bounded execution, result validation and orchestration are
separate modules, with one thin CLI. Production HLS, simulator numerical
components, frozen plugins and figure packages are unchanged.

The [SST/Spine extraction checkpoint](../../../repository/sst_spine_refactor/README.md)
passed exact regression before this new control work. Existing
rejected fixtures are preserved there and cannot be admitted as study samples.
