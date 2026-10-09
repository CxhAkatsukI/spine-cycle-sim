# Finite PMA / Original A4 Control

## Scope

This checkpoint compares original compact-input A4 with a finite PMA adapter
feeding exactly the same original A4 downstream. It is a source-functional
and finite-resource timing-prediction control. It does not reproduce FPGA
stage time, either publication's speed, original GraSU-produced input, the
current routed K4 placement, or full-system host orchestration.

All eight normal finite executions pass under the fixed
[contract](../../../../configs/experiments/pma_regraph_finite_control_v1.json).
Boundary and skewed whole-path UBSan executions retain identical complete
observations. The result status is
`FINITE_A4_B_FUNCTIONAL_PASS_TIMING_PREDICTED`, not a publication-speed match.
Accepted run: `results/upstream_stage_controls/finite_adapter_final_v1`. The owning
[implementation guide](../../../implementation/grasu_regraph/finite_pma_original_a4.md)
explains the reader, shared downstream, explicit timing assumptions, and windows.

Review the [results](finite_pma_results.json),
[raw/indexed delivery verification](finite_pma_verification.json), and
[preservation and postchecks](finite_pma_preservation.json) together. The
[raw archive](raw_finite_pma.tar.gz) retains nonaccepted preflights as well as
the formal matrix. It does not relabel a schedule-informed model as measured
hardware timing.

## Complete Normal Matrix

These are predicted resident one-iteration cycles, not FPGA measurements.
`B/A4` is elapsed-cycle ratio, not speedup of the complete G+R system.
All eight rows pass full state and ledgers; each normal/reverse pair has
identical complete observations, not only identical elapsed cycles.

| Case | Matched compact A4 cycles | PMA B cycles | Modeled B/A4 |
| --- | ---: | ---: | ---: |
| Boundary | 113,714 | 32,235,965 | 283.483 |
| Boundary reverse | 113,714 | 32,235,965 | 283.483 |
| Boundary, two state parents | 437,317 | 32,343,507 | 73.959 |
| Boundary, memory latency 128 | 118,247 | 60,469,345 | 511.382 |
| Skewed | 35,506 | 4,863,332 | 136.972 |
| Skewed reverse | 35,506 | 4,863,332 | 136.972 |
| Amazon | 886,840 | 701,285,374 | 790.769 |
| Amazon reverse | 886,840 | 701,285,374 | 790.769 |

| Input | Row-word accesses | Logical row bytes | Actual modeled row-bus bytes | PMA bytes | B/A4 input-read ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Boundary | 1,572,888 | 12,583,104 | 100,664,832 | 8,388,864 | 103.793 |
| Skewed | 262,152 | 2,097,216 | 16,777,728 | 262,208 | 258.997 |
| Amazon | 35,295,600 | 282,364,800 | 2,258,918,400 | 174,241,024 | 58.875 |

These large ratios expose substantial input-representation work in this
control: it visits every source in every original A4 task, rereads row lines,
and emits sixteen-slot source padding. Amazon has 48 tasks, 5,158,388 logical
edges and 43,560,256 physical PMA entries. Compact A4 has 5,165,928 padded edge
entries. This is neither evidence that the current routed K4 adapter is
790 times slower nor a measured performance match to original ReGraph. It
identifies costs that must be controlled before such a claim. Timing-model
assumptions add uncertainty beyond the conserved traffic difference.

## Admission And Preservation

Before edits, all eight A4 executions were freshly compared with the accepted
previous checkpoint. The baseline retains full stdout, state/ledger analyses,
binary/source identities, and the existing user patch. The new run builds in
a fresh Release directory. Both the legacy two-parent compact invocation and
the matched sixteen-parent invocation must preserve every baseline observation.
Only the matched invocation's new credit field is removed for that comparison.

Every completed B row must pass independent CSR pre-Apply sums, all four full
state replicas and allocation guards, exact logical work, request/response
conservation, drained finite queues, and complete task/publication windows.
Reverse-registration controls must equal normal execution, including cycles,
traffic, stalls, windows, and full state. State-parent and latency pressure
controls retain the same state and cannot silently disappear from the matrix.

Separate normal/repeated/UBSan calls to the pinned, unmodified HLS adapter and
the finite reader compare every packet word at cache thresholds zero, one,
and three. Stale copies have deliberately different payloads. The complete
whole-graph PMAs are all-hot; the routing fixtures, not those whole graphs,
provide cold/stale-copy evidence. Full-composition UBSan covers the boundary
and skew fixtures, not Amazon.

All 37 formal bounded steps pass. A fresh Release build passes 14 C++ tests;
164 focused Python tests and 15 repository-organization tests also pass.
An additional reader UBSan build exercises pressure, registration order,
capacity, latency, routing, and rejection controls without diagnostics.
All 2437 protected files and the frozen production plugin remain unchanged.
Existing numerical/SST bodies are unchanged; the new input model belongs to
a separate library. The old SST/FPGA matrices were preserved, not rerun.

Maximum individual formal-process RSS is 1,275,908 KiB, approximately 1.22 GiB.
Amazon normal and reverse subprocess wall times are 1609.28 and 1572.51 seconds.
The sum of all formal subprocess wall times is 4050.97 seconds, not campaign
elapsed time because B jobs overlap. CPU affinity is inherited, not pinned;
these wall times are execution cost, never accelerator performance evidence.
All eight declared normal rows completed without timeout or capacity failure.

## Timing And Traffic Interpretation

The HLS lowered schedules and top RTL show one 64-byte row transaction per
8-byte row-word access, including repeated reads of the same aligned line.
The input does not reuse a row cache line. Each selected PMA segment likewise
reads one 64-byte beat. Earlier source-packet logical byte counts remain valid
in their own scope but are not physical bus counts.

Row scans, dummy slots, and overlapping downstream execution are reported
separately. A sparse graph can have small useful compute work and substantial
empty-source scanning. The common resident window ends only after input drain
and acknowledged publication. A frontend can finish useful work before the
reader finishes its trailing empty rows. Union/intersection window lengths
are descriptive overlap metrics, not additive stage latencies.

All overhead values are `(modeled B cycles / matched A4 cycles - 1) * 100`.
They must not be quoted as measured FPGA integration overhead. In particular,
this original-A4 task-assignment control is not the routed K4/23-channel PMA
layout used by the hardware matrix. The common 210-MHz comparison clock is
conceptual; the inspected adapter packet targets 150 MHz and does not prove
210-MHz timing closure. Measured FPGA cycles and publication-rate errors stay
unset throughout the report.

## Reproduce

Use a fresh output directory and retain the pre-edit baseline. The raw package
will include the baseline manifest, full logs, small packet captures, inspected
HLS evidence, and input/state hash indexes. Large inputs, full state arrays,
toolchain binaries, and external checkouts are indexed rather than embedded;
the package is not a standalone toolchain distribution.

```bash
python3 scripts/run_pma_regraph_control.py \
  --adapter-source /home/chuxiao/grasu-regraph-integration/kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp \
  --hls-packet /data/tmp/chuxiao/grasu_regraph_sharded_k4_cc_hw_d886f42_20260806 \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --input-run results/upstream_stage_controls/original_host_inputs_final_v3 \
  --baseline results/upstream_stage_controls/finite_adapter_baseline_v1 \
  --out results/upstream_stage_controls/finite_adapter_reproduce
python3 -m unittest discover -s tests -p test_pma_regraph_control.py
```

Two independent bounded B processes may run concurrently, each with a 4-GiB
address-space limit, 128-MiB stack, and 3600-second timeout. The runner requires
the aggregate 8-GiB limit plus a 16-GiB reserve before starting them. Compile
parallelism is two. Each row records wall time and maximum process RSS, kept
separate from simulated device cycles. Failed preflights and any formal
timeouts remain visible; none count as accepted matches.

## Remaining Questions

Original G finite timing and paper-eight-slot geometry, graph-selected original
R publication admission, adapter physical timing, and measured host/system C
composition remain separate tasks. Passing this control cannot compensate
for missing evidence on those paths.
