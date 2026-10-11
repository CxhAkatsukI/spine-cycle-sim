# Real-Topology SSSP Resident-Round Control

## Question

Can the independent four-Little control consume the author's unchanged DBG
vertex permutation and task assignment, execute the same weighted SSSP round
as the actual sharded-K4 model, and preserve all old PR behavior? This is the
next gate after the [small correctness control](../sssp_control/README.md),
not a replacement for the [actual K4 FPGA evidence](../../model_sync/sst/input_residency/README.md).

## Fixed Scope

- Input: the repository's real-derived compact Amazon slice, 650 vertices
  and 1,280 unique directed weighted edges. External IDs are compacted.
- Layout: the pinned unmodified author-host probe performs DBG and dense
  four-Little task assignment. Original PR captures remain untouched; separate
  overlays carry SSSP weights and state. This is a local SSSP UDF extension,
  not an original-publication SSSP reproduction.
- Three scenarios: cold source; converged old graph with outgoing source-0
  weights decreased by 16 and source 0 reactivated; and an inactive negative
  control. The inactive arm deliberately does not propagate the changed graph.
- Exactly one synchronous resident round, not update-to-convergence. Both
  paths read the same old state and weighted logical graph. All 65,536 padded
  state words are checked against an independent synchronous oracle.
- Window: first component tick through all primary/source-state write
  acknowledgements. Host preparation, DMA, GraSU update and orchestration are
  outside this component diagnostic.
- Fixed mock service: 150 MHz, 32 channels, one issue per cycle per channel,
  32 outstanding and 32 response credits per channel. Latency is separately
  tested at 64 and 128 cycles; neither is fitted to the result.
- Registration order is reversed for every scenario/service combination:
  twelve runs, with identical complete outputs, counters and cycle counts
  required for each forward/reverse pair.

## Timing And Resource Limits

The local SSSP Apply synthesis schedule places old-state AXI read acceptance
at SV72 and comparison/output at SV73: one unstalled post-response cycle,
II=1. The report's pipeline depth of 74 includes the scheduled memory path;
it is not an extra 74-cycle delay after the modeled memory response. The
reference is a local 1-Little/1-Big 300-MHz synthesis, not an A4 board
measurement. Backpressure can increase observed response-to-output time.
The optional response-anchored implementation retains ordered responses and
bounded credits. Existing default Apply timing is unchanged.

Equal mock service is **not equal resource provisioning**. A4 has thirteen
logical AXI masters and writes four state replicas; actual K4 has nine
masters and writes primary state, two source replicas and a four-byte status.
A4's inherited masters share read/write credits; K4 uses independent
read/write credits. Queueing, partition assignment, input padding and merger
topology also differ. This input has only one destination partition, so K4
uses worker 0 rather than filling four workers. A cycle ratio is therefore
diagnostic only, not admitted integration overhead or publication matching.

## Validation

The C++ executor checks every replica, oracle-derived active population,
dummy/live work, complete read/write byte decompositions, request/completion
and beat conservation, acknowledgements, and drained resources. A4 writer
guards must remain unchanged. All seven complete padded output files must
have the same hash. Memory latency may change cycles but not state or traffic.

Four old component outputs, two complete original-source comparisons and
three complete original PR graph executions must remain byte-identical,
including stdout cycles/counters and every state file. New builds do not
overwrite the default SST plugin.

Geometry admission still depends on the pinned author's probe and the
separate SSSP task/CSR correspondence checks. The geometry-only loader is
for unchanged author PR captures, not prepacked weighted SSSP input. Its
layout validation accumulates counters and is called once while loading;
callers must not revalidate the same object. PR arithmetic and SSSP state
remain independently checked rather than treating geometry admission as
an algorithm-correctness gate.

## Results

All twelve declared runs pass. Reversed registration order gives identical
cycles, complete states and traffic. The table shows the six forward runs;
the archived report contains every reverse run as well.

| Initial-state scenario | Memory latency (cycles) | A4 cycles | Actual-K4 model cycles | K4/A4 diagnostic ratio | Active output vertices |
| --- | ---: | ---: | ---: | ---: | ---: |
| Cold | 64 | 142,141 | 117,481 | 0.827 | 10 |
| Warm update | 64 | 142,141 | 117,481 | 0.827 | 10 |
| Inactive negative control | 64 | 142,141 | 117,481 | 0.827 | 0 |
| Cold | 128 | 273,881 | 161,030 | 0.588 | 10 |
| Warm update | 128 | 273,881 | 161,030 | 0.588 | 10 |
| Inactive negative control | 128 | 273,881 | 161,030 | 0.588 | 0 |

These states are not identical across the three scenarios; the warm arm
starts from old converged distances and changes ten outgoing weights.
Identical cycles here reflect fixed-round scanning and complete padded state
publication, not proof that cold and warm convergence cost the same.

The cycle ratios do **not** reproduce the hundreds-fold PMA slowdown from
the earlier original-task/PMA control. That control's pathological layout is
not an interchangeable measurement of the actual-K4 implementation. This
small diagnostic also does not prove that all large-graph adapter costs
have disappeared: most work here is padded-state publication, only one K4
worker runs, and A4 writes an extra state replica.

Traffic is invariant across scenarios and the two memory latencies:

| Quantity | A4 | Actual-K4 model |
| --- | ---: | ---: |
| Read payload bytes | 403,520 | 344,832 |
| Write payload bytes | 1,048,576 | 786,436 |
| Valid logical edges | 1,280 | 1,280 |
| Physical edge entries | 1,288 | 2,064 (258 eight-edge packets) |
| Dummy edge entries | 8 | 784 |

K4 separately accounts for one extent read, 650 row reads, 129 segment
reads, 512 source lines and 4,096 old-state reads. Each read is 64 bytes;
primary plus two source-state replicas and a four-byte status explain every
write byte. These are conserved payloads, not measured HBM bus energy.

## Rejected Attempts And Default Preservation

- `run-v1` failed compilation because the new test needed an explicit
  validated 12-bit weight conversion to the edge ABI's 16-bit field. It ran
  no matrix and contributes no numerical result.
- `run-v2` passed the old component/source and three whole-graph regressions,
  then rejected author PR initialization on this small slice. The unchanged
  author probe reports 81 arithmetic rejections: its fixed-point PR product
  exceeds the original signed range. This is not an SSSP correctness failure.
- `run-v3` separates geometry/capture validation from PR value validation.
  The default PR loader and admission still enforce the strict old arithmetic
  check. A negative execution of the unchanged PR captures must fail with
  `initial PR iteration exceeds original signed arithmetic domain` and leave
  no output. Separate weighted-SSSP overlays pass their own oracle.

No original capture or PR arithmetic is replaced to make the test pass.
The three old whole-graph cases (`skewed_sources`, `boundary_ring`, and the
735,324-vertex Amazon input) retain every state word and exact cycle/counter
stdout. This large PR case is a regression gate, not a new SSSP measurement.

## Delivery

The [results](evidence/results.json), [verification manifest](evidence/verification.json)
and [sealed raw archive](evidence/raw_sssp_real_round.tar.gz) form one handoff.
The archive contains author captures, all SSSP overlays, all seven complete
state replicas for every run, full old/new PR state files, failed-attempt
reports/logs, and final verification logs. Local binaries, author tools and
HLS synthesis files remain hash-indexed external dependencies. The legacy
whole-graph input files are indexed at packaging time; their prebaseline
hashes were not recorded, so no retroactive input-freeze claim is made.

The numerical run uses GCC 15.2.0 Release. Its maximum reported single-process
RSS is 0.439 GiB and minimum initial available memory is 47.38 GiB. These
`wait4` values are not simultaneous process-tree RSS. Final Python verification
additionally uses a live process-tree watchdog: the sampled tree peak is
1.97 GiB and minimum available system memory is 45.46 GiB, against an 8-GiB
tree budget and 16-GiB live reserve. The complete Release build, all 28 CTest
tests and all 280 selected Python tests pass. The default SST plugin stays
at SHA-256 `9a26e1fb51ecf7b99ccf0784c9e5bbc459cf857d293add557b9c52770b2c9d79`.

## Reproduction

Run from the simulator worktree root with fresh build/output directories:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.study \
  --build build/original-a4-sssp-real-round-reproduction \
  --output results/original-a4-sssp-real-round-reproduction \
  --component-baseline /data/chuxiao/experiments/original_a4_sssp_control_20261011/baseline \
  --whole-baseline /data/chuxiao/experiments/a4_actual_sssp_real_round_20261011/baseline \
  --hls-udf /home/chuxiao/regraph/ReGraph/acc_udfs/sssp/l2.h \
  --probe-report results/upstream_stage_controls/original_host_inputs_final_v3/report.json \
  --probe results/upstream_stage_controls/original_host_inputs_final_v3/a4/probe \
  --apply-solution /data/chuxiao/regraph/ReGraph_sssp_hw_fixed_scratch/_x/kernelApply.hw.xilinx_u55c_gen3x16_xdma_3_202210_1/kernelApply/kernelApply/solution
```

The external probe, its dependencies, local HLS reference, schedule files,
compiler/cache, source and binary identities are recorded. Missing or changed
dependencies reject admission; they are not silently replaced by new versions.
Compilation is limited to two workers; each subprocess has an 8-GiB
address-space limit with a 16-GiB initial system-memory reserve and timeout.

Final verification builds every target, runs CTest with two workers, and
selects `test_original_regraph*.py`, `test_sharded_k4*.py`, and
`test_repository_structure.py` for Python discovery. Exact command arrays
and exit/resource records are archived under `verification/`. Build/CTest
use `upstream_controls.execution.run_bounded`; Python uses the existing
`sharded_k4_stages.link_runtime.run_link` process-tree watchdog with a
900-second timeout, 8-GiB tree budget, and 16-GiB live reserve. This avoids
mistaking a single-process address-space cap for a whole-test-tree cap.

After running the documented final verification gates, package to a fresh
directory, without overwriting numerical evidence:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery \
  --run /data/chuxiao/experiments/a4_actual_sssp_real_round_20261011/run-v3 \
  --destination results/sssp-real-round-delivery-reproduction \
  --component-baseline /data/chuxiao/experiments/original_a4_sssp_control_20261011/baseline \
  --whole-baseline /data/chuxiao/experiments/a4_actual_sssp_real_round_20261011/baseline \
  --verification /data/chuxiao/experiments/a4_actual_sssp_real_round_20261011/verification-v3 \
  --attempt /data/chuxiao/experiments/a4_actual_sssp_real_round_20261011/run-v1 \
  --attempt /data/chuxiao/experiments/a4_actual_sssp_real_round_20261011/run-v2
```

This checkpoint alone cannot close original-publication reproduction,
multi-partition K4 throughput, complete G finite timing, real HBM timing, or
the final resource-audited A4 versus integrated K4 comparison.
