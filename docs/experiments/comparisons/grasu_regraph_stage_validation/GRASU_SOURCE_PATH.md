# Original G Kernel Composition

## Conclusion

Eight predeclared prepared-PMA fixtures pass the original GraSU source16
search, dispatch, URAM-cache and DDR update paths. Two normal repetitions and
one UBSan execution of every case produce identical complete protocol/state
results. All 11 actual-output corruption controls are rejected. The earlier
cache-only control's stdout and stderr remain byte-identical to its frozen
archive. This is functional source composition, **not** a finite-cycle model,
original host validation or a published-throughput match.

Accepted run: `results/upstream_stage_controls/grasu_source_path_final_v1`.
Source: clean author revision `e95da256be9e7f2361449323b6fe0abf98c1b152`.
Compilation: GNU g++ 15.2.0, `-std=c++17 -O1 -g0`, Vitis HLS 2024.1 headers,
GMP; instrumentation adds `-fsanitize=undefined -fno-sanitize-recover=all`.
Namespace wrappers only separate duplicate helper names; author bodies are
unchanged. The [implementation guide](../../../implementation/grasu_regraph/original_grasu_source_path.md)
maps each responsibility to its code owner.

## Scope And Results

The fixture reserves 262,208 global segments: 131,072 hot plus 32 cold segments
per half. A segment holds sixteen 32-bit slots. It has two source ranges and
constructed search tables, not a real temporal graph processed by the original
trace-aware host. Valid insertions have reserved capacity; deletes are present.
Segments start with three live values and reach at most five in this matrix.
Empty input is not an empty-segment test; empty/full segment occupancy and
rebalance need separate controls before admitting a broader update workload.

| Case | Batches | Updates | Search reads | Cache-even / DDR-even / cache-odd / DDR-odd updates |
| --- | ---: | ---: | ---: | --- |
| Empty | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| One | 1 | 1 | 19 | 1 / 0 / 0 / 0 |
| Three | 1 | 3 | 57 | 2 / 0 / 1 / 0 |
| BIPA group boundary 65 | 1 | 65 | 1,223 | 32 / 1 / 32 / 0 |
| Search lane boundary 257 | 1 | 257 | 3,347 | 65 / 64 / 64 / 64 |
| Hot only | 1 | 192 | 3,648 | 96 / 0 / 96 / 0 |
| Cold only | 1 | 192 | 1,344 | 0 / 96 / 0 / 96 |
| Mixed, three batches | 3 | 896 | 11,648 | 224 / 224 / 224 / 224 |

Counts are per repetition. The 65-update case crosses a 16-lane BIPA group
after four-way input splitting; 257 updates exercise all 256 search lanes
and wrap one lane. First/last hot rows cover all sixteen cache banks of both halves, and
the cold region covers both DDR subpaths and every polling lane. Empty input
still checks termination and the entire unchanged state.

C++ checks 83,906,560 buffer-slot observations per complete matrix: every
slot in all four physical copies after every batch, not just touched segments.
Python independently checks every recorded search request and 96-bit packet,
the expected dispatch route, and all 4,195,328 final merged slots of each case.
Every per-lane search end and replayed BIPA stream is drained and checked.

The source calls are decomposed to avoid pretending that ordinary C-simulation
implements concurrent HLS DATAFLOW. Original `binary_search` receives immediate
memory responses through test delegates; its requests are replayed through
original `bipa` and every returned value checked. Original reader, merger,
dispatch and cache/DDR functions are invoked unmodified. The concurrent
top-level `bin_search` event window and finite stream timing are not tested.

## Traffic Finding

Each invocation of both cache halves preloads 16 MiB and writes back 16 MiB
in total, including an empty batch. This 32-MiB cache transfer is fixed by
original loops, not proportional only to successful updates. The mixed
three-batch row therefore implies 48 MiB cache reads plus 48 MiB cache writes,
and 28,672 bytes each of logical cold read/write accesses.

These are loop-derived or logical source accesses, not measured AXI traffic,
burst transactions or memory-service time. Search requests count 8-byte
accesses; update records count 8 bytes. No device cycles or rate are inferred
from these counts. A future original-G timing model must account for full
cache transfer and concurrent search/update/backpressure, not substitute the
production integration's direct-HBM policy.

## Validation And Preservation

The 29 bounded compile/run/test steps take approximately 91 seconds summed
wall time. Maximum individual process RSS is 363,188 KiB, below 0.35 GiB.
Each launch is sequential within this matrix, capped at 3 GiB address space,
128 MiB stack, with 16 GiB available-memory reserve; compile timeout is 300 s
and run timeout 180 s. Resource logs use `wait4` maximum individual-process RSS,
not a simultaneous process-tree sum. Wall time is execution cost, not a
hardware measurement.

Twelve focused Python tests pass. Actual-source-output negative controls
damage the header, packet, operation, route, memory address/value, extent,
counter type, untouched final state and diagnostic stream; every gate rejects.
UBSan passes all eight cases without a sanitizer diagnostic. The unmodified
author's exact two-line 512/32-bit OR warning is retained once per insertion;
missing, additional or different diagnostics fail. Raw warning logs are included.

The source/evidence baseline contains 126 preexisting files, all unchanged.
Additional core, protected-evidence, plugin and organization checks are recorded
in [preservation verification](grasu_source_path_preservation.json): 13 existing
C++ tests and 150 focused Python tests pass (135 component/study tests and
15 organization tests). The unchanged core build is reused, not rebuilt.
No numerical
production/SST component is edited. The previous SST/Spine matrix is preserved,
not claimed to have been rerun by this optional author-source study.

Historical attempts are included and labeled nonaccepted: preflight v1 failed
on the missing `include/etc` path; v2 stopped on the original width warning;
v3 passed before actual-output rejection/delivery additions were finalized.
The final matrix reruns all cases under the delivered source identities.

## Reproduce

Use the clean GraSU checkout from the [study guide](README.md), Vitis headers
and GMP. The archived baseline permits reproduction without a previous local
results tree; verify the archive against its manifest before extracting it.
Use fresh output directories:

```bash
mkdir -p results/reproduce_grasu_source
tar -xzf docs/experiments/comparisons/grasu_regraph_stage_validation/raw_grasu_source_path.tar.gz \
  -C results/reproduce_grasu_source baseline/baseline.json
python3 scripts/run_original_grasu_source_path.py \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --baseline results/reproduce_grasu_source/baseline \
  --out results/reproduce_grasu_source/run
python3 -m unittest discover -s tests -p test_original_grasu_source_path.py
```

The [raw package](raw_grasu_source_path.tar.gz) contains contracts, dependency
identities, all protocol captures, run/resource logs, baseline and historical
attempts. [Results](grasu_source_path_results.json) and
[archive/member verification](grasu_source_path_verification.json) identify
every final full-state capture; these 16-MiB states and compiled binaries are
regenerable and not archived. Every final state is rechecked before delivery.

## Remaining Gates

Original host reservation/reordering is not executed here. Inspected
`pma_dynamic_graph.hpp` includes size-unchecked vector indexing while consuming
the last edge; original host buffer initialization/merge boundaries also need
their own guarded controls. This is a source-audit concern, not an observed
FPGA failure. Sequential C-simulation also does not prove in-place DDR RAW
safety across aliased AXI bundles or finite-channel liveness.

Next admit and check that host boundary, then implement separately owned finite
G resources using the recovered HLS constraints. Keep paper8 versus source16,
temporal trace/batches, successful-update numerator, clock and profiling event
window explicit. Publication performance error remains null. B must still reuse
the same original A4 downstream, and C requires independent G/B plus measured
host orchestration; a matching system total cannot replace these stage gates.
