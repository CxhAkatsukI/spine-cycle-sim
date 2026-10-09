# Original Big Routing/Gather Checkpoint

Scope: independent original-ReGraph PR dispatch, three-layer omega network,
eight destination banks, result packing and three-way global merge. This is
a component checkpoint on the way to original mixed R, not a publication
speed match. See the [implementation contract](../../../implementation/grasu_regraph/original_regraph_big_gather.md)
for resource ownership and timing assumptions.

## Accepted Results

Authoritative run: `results/upstream_stage_controls/big_gather_final_v2`.
Its 29 bounded execution steps pass. Both model executables repeat exactly
and match independent UBSan/assertion builds without diagnostics. The
complete author capture is 8,388,608 bytes, SHA-256
`c738aa51af28f1c438b9f3bdc748d993b6f63e9957d7aba8c21e0ef8aa8dce51`.

| Model case | Predicted cycles |
| --- | ---: |
| Three Big, distributed | 33,174 |
| Reverse registration | 33,174 |
| Reused zero-burst partition | 32,796 |
| Reused nonzero partition | 33,174 |
| Three Big, one-bank hotspot | 40,604 |
| Depth-one queues and delayed slow sink | 279,371 |
| One in-flight Gather operation | 87,205 |
| Single Big, distributed | 33,132 |

These cycles exclude edge/source memory and Apply/writeback. The hotspot
and pressure responses confirm finite model resources are operative; they
do not calibrate the original hardware. Three damaged captures are rejected.
All four old component outputs and eight complete-A4 rows remain byte-exact,
including all four state replicas. Eleven CTest tests and 117 focused Python
tests pass. The main study takes about 159 seconds of aggregate bounded-step
wall time; maximum individual-process RSS is 689,444 KiB, not a measured
simultaneous-process sum. No graph workload was reduced for memory safety.

Deliverables are [results](big_gather_results.json),
[archive verification](big_gather_verification.json),
[preservation checks](big_gather_preservation.json) and
[raw evidence](raw_big_gather.tar.gz). The archive has 126 indexed files,
157,537 bytes, SHA-256
`f583a57bd78234fd2ebd521ece6f40853ddfc5b07b39ca880d6f600828b550e3`.
Its complete member contents were independently hashed after packaging.

The first final attempt, `big_gather_final_v1`, is retained as a failed probe
compilation: the Vitis stream API has no const `empty()` overload. Only the
new probe's conservation-check loops were corrected. The preflight run is
also retained; neither is substituted for the accepted final run.

## Acceptance

The fixed matrix checks normal destination distribution, reversed component
registration, zero/nonzero partition reuse, a one-bank hotspot, depth-one
queues with a delayed slow consumer, one in-flight Gather operation, and a
single-Big merger. Every output is checked against an independent per-update
sum. All registered queues, switch data/end tokens, bank updates, writes,
drain and clear work must conserve. Pressure must change stalls and cycles,
not just preserve final values.

A separate probe invokes the pinned author's unmodified `acc_gather.h` and
generated three-way merger, without using simulator routing or bank code.
It captures four complete partitions in order: distributed, zero, hotspot,
distributed again. Comparison covers 2,097,152 words, including every zero
destination and every bank boundary. Author C-simulation is functional
evidence, not a finite-stream or FPGA timing measurement.

The study also repeats both model executables, runs them under UBSan and
libstdc++ assertions, and rejects changed, truncated and excess captures.
It compares all four frozen old component outputs and all eight accepted
whole-A4 graph executions, including every output replica and complete
stdout containing cycles/traffic/stalls/task lifecycles. Earlier accepted
artifacts are read, never rewritten. Production SST numerical runs are not
rerun for this isolated original-R extension.

## Reproduce

Start from the source pins in [the study guide](README.md). Vitis headers,
GMP, G++ and Python 3.11 for the author generator are required. The runner
uses sequential bounded processes, two Release build jobs, a 3-GiB process
address-space limit, 128-MiB stack and 16-GiB available-memory reserve. It
refuses to overwrite an output directory and retains unsuccessful attempts.

Before adding the Big code, the four existing component outputs and all
existing original-R source hashes were frozen in
`results/upstream_stage_controls/big_gather_baseline_v1/baseline.json`.
The accepted A4 reference is
`results/upstream_stage_controls/a4_execution_final_v3`; reproduce that
[checkpoint](A4_GRAPH_EXECUTION.md) first in a fresh workspace. For the
pre-change component baseline, use a detached `1bd3fff` worktree and run
its four original-ReGraph test executables with saved stdout/stderr and
resource records; the delivered raw archive retains the exact local baseline.

```bash
python3 scripts/run_original_regraph_big_validation.py \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --baseline results/upstream_stage_controls/big_gather_baseline_v1 \
  --out results/upstream_stage_controls/reproduce_big_gather
python3 -m unittest discover -s tests -p test_original_regraph_big_validation.py
```

Package only after the full study passes, using
`spine_cycle_sim.experiments.original_regraph_validation.big.delivery.deliver`.
It rechecks raw runs, complete source comparisons, repetitions, UBSan,
compiler dependencies, tested binary/source hashes and all legacy gates.
The package excludes binaries, author trees, regenerable damaged captures
and A4 replica payloads; the latter are hash-indexed in the results.

## Remaining Work

Connect Big's own request-dependent cacheline source path and its original
physical memory ports, then execute the admitted full mixed Amazon layout.
Do not treat Big as a renamed Little or a Little timing multiplier. Clock,
graph-selected original-paper topology, event denominator/window and actual
memory service still require admission before an approximately 10% paper
performance comparison. Original G finite timing and matched adapter control
B remain separate incomplete milestones.
