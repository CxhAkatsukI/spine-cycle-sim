# Whole-Line Input Versus Original-Style A4

## Findings

All 24 predeclared runs pass complete-state and traffic checks. Original A4,
the old K4 composition, the extracted legacy harness and skip-empty timing
reproduce their frozen results exactly. Both registration orders execute
all four K4 workers and return identical cycles, counters and complete states.

| Resident scenario | Memory latency | Original A4 cycles | Legacy K4 cycles | Skip-empty K4 cycles | Whole-line K4 cycles |
| --- | ---: | ---: | ---: | ---: | ---: |
| Cold source, one round | 64 | 668,278 | 23,478,378 | 17,745,396 | 17,326,124 |
| Warm update, one round | 64 | 668,278 | 23,478,378 | 17,745,396 | 17,326,124 |
| Warm update, one round | 128 | 1,292,225 | 36,980,821 | 31,247,839 | 30,796,315 |

The reverse-registration runs reproduce each displayed row. Cold and warm
output states differ, although their one-round work and cycles coincide.
The whole-line candidate reduces directory requests from 1,032,172 to
129,022 (approximately 8x) and all input reads from 101,741,312 to
43,939,712 bytes (56.81%). Valid edges, padding, source-state reads and
publication writes are unchanged. Every output replica has 262,144 words
and matches the complete frozen oracle.

Whole-line reads reduce total predicted time by only 1.44--2.36% relative
to skip-empty, or 16.72--26.20% relative to legacy K4. **The candidate still
takes 23.83--25.93 times the A4 cycles in this model.** This is a negative
finding: the directory optimization does not recover original-A4 performance.
It is not a measured FPGA slowdown, an isolated adapter overhead, or a
claim about the Figure 7 hardware comparison.

Invocation traces confirm all four adapters start at cycle zero. At latency
64 their lifetimes end at 17,184,522, 15,439,346, 11,219,294 and 6,952,774
cycles. The last gather ends at 17,325,541 and total completion is
17,326,124. The unchanged 7,609,792 physical slots contain 1,450,899 live
and 6,158,893 dummy edges; A4 has 1,451,712 physical entries. Padding,
occupied-row service and downstream dependencies remain investigation
targets. These overlapping lifetimes do not establish exclusive stall costs.

## Scope

This is a **fixed-model, one-resident-round control**, not FPGA timing,
propagation to convergence, a strict resource match, or a reproduction of
published ReGraph throughput. It extends the
[four-partition control](../../../matched_a4/sssp_partition_round/README.md)
without replacing that frozen experiment or relaxing its validator.

The compared paths are original-style four-Little weighted SSSP (A4),
legacy actual-layout K4, K4 without the measured empty-helper exit wait,
and K4 with both skip-empty and whole-line directory reads. The last path
models the [production HLS candidate](../README.md), not the independent
PMA-plus-original-A4 layout that previously predicted a 791x slowdown.
There are no fitted timing multipliers.

The graph, author's DBG/task capture, positive 12-bit weight overlay, old
converged state and source-0 update are pinned to the preceding control:
258,046 vertices, 1,450,899 edges, sixteen original-A4 tasks and four K4
destination shards. Original external IDs 1--258,048 are selected before
DBG; internal holes are not silently compacted. The warm arm has three
decreased outgoing weights and starts with the same reactivated source in
both paths. A cold-source control is also retained.

Timing starts at the first component tick with input/state resident and ends
after all state-write acknowledgements. GraSU updates, preparation, DMA and
host orchestration are outside this window. Each run executes exactly one
synchronous round, even when the source state is warm. This is not the
hardware Figure 7 update-to-convergence comparison.

The shared memory service is a fixed MockMemoryBackend: 150 MHz, 32
channels, one issue per channel per cycle, 32 outstanding and response
credits per channel. Latencies 64 and 128 are sensitivity settings, not
DRAMSim3 or fitted board latency. A4 has thirteen logical AXI masters,
four state replicas and shared read/write credits. K4 has nine masters,
three replicas plus status and independent read/write credits. Layout,
scheduling and backends also differ. Therefore a cycle ratio is a diagnostic
of the full modeled paths, **not isolated adapter overhead**.

## Reviewable Ownership

`cpp/tests/routed_regraph/round_execution.hpp` owns the shared K4 test
composition and complete-state/conservation checks. The old empty-helper
CLI and new whole-line CLI only parse arguments and choose explicit options.
The original A4/legacy executable remains unmodified. Before extraction,
the old harness and relevant numerical sources were archived with SHA-256
`e5ea73399606cf911964e516bddfd74936076c9b462064069e5c268963b07a36`.

The Python owner is
`spine_cycle_sim/experiments/sharded_k4_stages/row_line/a4_control/`:

| Module | Responsibility |
| --- | --- |
| `contract.py` | Frozen historical identities, exact matrix and limits |
| `preparation.py` | Declare source differences and copy complete inputs/oracles |
| `execution.py` | Fixed compiler/build/run commands and executable identities |
| `analysis.py` | Exact replay, independent traffic and full-state admission |
| `study.py` | Bounded orchestration and source/tool preservation |
| `recheck.py` | Recompute admission from raw frozen evidence |
| `delivery.py` | Seal and independently recheck a relocatable archive |

The numerical-version declaration permits only the already introduced
adapter header/implementation changes and the explicit test-harness
extraction. Earlier report hashes remain fixed. Both the unmodified
original/legacy executor and the extracted legacy harness are rerun; all
cycles, counters and complete output states must match their historical
baselines exactly. The skip-empty arm must also reproduce its preceding
complete result exactly.

For whole-line admission, the expected directory request count is independently
reconstructed as the sum of `ceil(visited_rows / 8)` over the four shards.
Only those requests and their corresponding read bytes may change. Extent,
segment, source-state, valid/dummy edge and state-publication work must remain
unchanged. Every primary/source output word is checked, not sampled.
Partition/worker invocation bounds require all four workers to execute.
Reversed component registration must preserve cycles, counters, invocations
and state; doubling memory latency must increase modeled time without
changing work or outputs. No gate requires the candidate to be faster.

## Reproduction

Use fresh output and delivery directories from the simulator repository root.
The pre-extraction archive is included in the delivered raw package.

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.a4_control.study \
  --output /data/chuxiao/experiments/fresh_whole_line_A4 \
  --pre-extraction /path/to/extracted/run/pre_extraction.tar.gz

python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.a4_control.delivery \
  --run /data/chuxiao/experiments/fresh_whole_line_A4 \
  --destination /tmp/fresh_whole_line_A4_evidence

python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.a4_control.delivery \
  --destination docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/a4_control/evidence \
  --verify-only
```

Execution also needs the pinned historical complete input/state paths recorded
in the manifest. A fresh machine can recheck the portable evidence without
those paths; a fresh execution requires restoring those dependencies first.
GCC 15.2.0 is explicitly selected. Release builds use two jobs; numerical
runs are serial and pinned to CPUs 112--113. Each numerical child has a
3-GiB sampled tree-RSS budget and 180-second timeout. The outer watchdog
has 8 GiB and 1,800 seconds; every level preserves 16 GiB available memory.
Pidfd-based sampled cleanup is not cgroup containment.

The default SST plugin, historical measured bitstreams, integration worktree
and paper are not changed by this control. Whole-line route/board admission
and the final resource/semantic-matched performance conclusion remain
separate gates; see the [route checkpoint](../route/README.md).

## Delivery And Verification

| Artifact | Contents |
| --- | --- |
| [Results](evidence/results.json) | Complete 24-run matrix, invocations, state hashes and admission decisions |
| [Evidence index](evidence/verification.json) | Every sealed file, archive hash and aggregate watchdog record |
| [Portable raw archive](evidence/raw_A4_control.tar.gz) | 500 files: complete inputs/oracles/states, executed sources, three binaries/build flags, historical bases and raw logs |
| [Regression index](verification/verification.json) | Accepted checks, command/resource records and preserved failed-test attempt |
| [Regression archive](verification/raw_regressions.tar.gz) | Raw regression logs and exact new test sources |
| [Interrupted development index](development/verification.json) | Original interrupted manifest/status and explicit non-admission |
| [Interrupted development archive](development/interrupted_attempt.tar.gz) | Sources and logs from the pre-matrix compiler-name check |

The portable numerical archive SHA-256 is
`c3b1364dfb67c613f7f36fcfb7e5ef70b1c7e3f04ddb04af981a0920ff872219`.
Its independently extracted raw recheck passes. Final regressions pass all
27 C++ tests, 324 sharded-K4 Python tests (including twenty new control/raw
evidence tests), 120 original-ReGraph tests and fifteen structure tests.
Document layout, generated catalogs and whitespace checks pass.

The initial development run was deliberately interrupted before numerical
cases because compiler display-name comparison used `c++` instead of the
historical `g++`. Its original `running` JSON is preserved: the old exception
handler did not catch `KeyboardInterrupt`. A separate interruption note and
watchdog exit -2 explicitly classify that attempt as non-admitted. The fresh
run uses explicit `/usr/bin/g++` and catches interruptions for future runs.

The first broader Python regression also stopped on a new test-harness
error: a temporary directory attribute shadowed `unittest.TestCase.run`.
The failed logs and exact failing test source are retained in the regression
archive. Renaming that attribute fixes the test runner; no numerical model,
input, frozen result or admission criterion changed to make the retry pass.

## Next Gate

Route the already checked whole-line XO only after the 40-GiB process-tree
budget plus 16-GiB live reserve is available. Check routed timing and paired
resident FPGA outputs/events before claiming any board improvement. Then
resolve the declared resource/window differences and compare original A4
with the actual optimized path. Investigate the remaining modeled padding
and occupied-row costs without fitting away the negative result above.
Neither this model control nor an aggregate timing match completes those gates.
