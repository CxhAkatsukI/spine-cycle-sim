# Empty-Helper Model Sensitivity

## Question And Evidence Boundary

How much of the frozen four-partition K4 prediction depends on the empty
helper's 73-cycle exit? This study changes only
`adapter.empty_segment_exit_cycles` from 73 to zero. The zero arm is an
**uncalibrated sensitivity experiment**, not a new production profile or a
claim about routed FPGA speed. Removing this term does not remove row
metadata reads, occupied segments, padding, or their backpressure.

The [paired RTL experiment](../README.md) supports bypassing the helper for
truly empty segment ranges. Its transactor timing is not an HBM service
calibration. The [production XO](../production/README.md) has passed compile
and ABI checks, but has not been routed or run on the board. These evidence
levels must not be combined into a measured whole-system speedup.

## Results And Reading Order

The final v2 replay passes all twelve cases. The legacy arm exactly
reproduces the frozen cycles; the zero arm preserves all three complete
state replicas and every non-cycle counter. Both registration orders give
identical results. All final cycles, counters and complete-state hashes also
equal the preceding pilot; v2 strengthens provenance, not numerical tuning.

| Initial state / mock latency | Legacy, 73 cycles | Sensitivity, zero cycles | Legacy / sensitivity | Time reduction |
| --- | ---: | ---: | ---: | ---: |
| Cold / 64 | 23,478,378 | 17,745,396 | 1.323x | 24.42% |
| Warm update / 64 | 23,478,378 | 17,745,396 | 1.323x | 24.42% |
| Warm update / 128 | 36,980,821 | 31,247,839 | 1.183x | 15.50% |

These are model cycles for one synchronous round. Identical cold/warm timing
does not assert identical convergence work: the configured scanner visits
the same layout in either single-round execution. The frozen A4 reference
takes 668,278 and 1,292,225 cycles at the two latencies. Even after this
single-term removal, K4/A4 remains **26.55x and 24.18x** in this diagnostic.
This neither establishes an FPGA slowdown nor isolates the remaining gap's
cause. In particular, do not attribute the residual ratio entirely to PMA:
the reference paths have different layouts, scheduling and memory resources.

The defensible conclusion is narrow: the empty-helper wait matters, but its
removal alone does not explain or close this fixed-model discrepancy. Row
metadata reads, occupied-segment processing, padding, downstream waits and
their overlap remain modeled. No production profile was changed or fitted.

| Read next | Contents |
| --- | --- |
| [Final results](evidence/results.json) | Twelve cases, exact counters, state hashes, commands and 248 source pins |
| [Final verification](evidence/verification.json) | Reconstructed admission and hash-indexed raw archive |
| [Raw evidence](evidence/raw_sensitivity.tar.gz) | Logs, all complete states, execution sources, standalone binary, compiler flags and watchdog records |
| [Regression verification](checks/verification.json) | 359 Python tests and 28 frozen-build C++ tests, with raw logs and reviewed test sources |
| [Prior pilot](prior-pilot-v1/verification.json) | Preserved first replay; superseded by v2 for execution-provenance closure |

The pilot recorded fewer reused-owner pins and did not rehash its executable
before every launch. It is retained as historical evidence, not presented as
meeting the final admission contract. V2 pins the reused partition/runtime
owners, checks executable identity before each launch and at completion,
and rechecks the frozen basis and production prerequisites after execution.
The final run took 337.85 seconds, peaked at 1.006 GiB sampled process-tree
RSS and retained at least 49.47 GiB available host memory. The Python and
C++ regressions took 65.84 and 50.98 seconds under separate three-GiB tree
caps. CTest replays the existing frozen Release build; the new isolated
harness was freshly built and exercised by the twelve real-input cases.

## Fixed Workload And Checks

The inputs are exactly those of the frozen
[four-partition A4/K4 diagnostic](../../../matched_a4/sssp_partition_round/README.md):
Amazon topology, 258,046 vertices, 1,450,899 logical weighted edges, four
destination partitions, and 262,144 padded state words per replica. Local
weights and old-state construction are specified in that package. This is
one synchronous SSSP round, **not batch-to-convergence**.

The twelve declared runs cover cold/64-cycle memory, warm-update/64-cycle,
and warm-update/128-cycle, each in forward/reverse component registration
order and with empty-exit 73/0. Both arms retain the frozen 150-MHz,
32-channel mock-memory service and every other numerical setting. The
window ends only after state publication and all request acknowledgements.

Acceptance requires:

- The 73-cycle control reproduces every frozen K4 cycle count and counter.
- All three complete state replicas match the frozen oracle hashes.
- The zero arm preserves all non-cycle counters, including read/write
  bytes, live/dummy edges, row/segment reads and active vertices.
- Registration order leaves full outputs, counters and cycles unchanged.
- Higher memory latency preserves results and traffic while increasing time.

The frozen A4 timing is a diagnostic reference, not a newly executed A4 arm.
The underlying A4/K4 memory-master topology and state replication are not
strictly resource matched. Neither arm establishes original-publication
matching, convergence performance, or a calibrated production candidate.

## Reproduction

The owning modules are
`spine_cycle_sim/experiments/sharded_k4_stages/empty_segment/sensitivity/`.
The isolated C++ harness is
`cpp/tests/routed_regraph/empty_segment/`; it reuses the immutable input
loader and numerical libraries without editing their frozen build lists.
Use a fresh output and a new standalone Release build:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.sensitivity.study \
  --output results/empty-helper-sensitivity \
  --basis /data/chuxiao/experiments/a4_actual_sssp_partition_round_20261011/run-v6 \
  --production /data/chuxiao/experiments/sharded_k4_skip_empty_segment_20261011/production-v2

python3 -m spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.sensitivity.delivery \
  --run results/empty-helper-sensitivity \
  --destination results/empty-helper-sensitivity-package

python3 -m unittest discover -s tests -p 'test_sharded_k4_empty_segment_sensitivity*.py'
```

Execution is sequential, with at most two compiler workers, an eight-GiB
outer sampled process-tree cap, a sixteen-GiB live-memory reserve and an
1,800-second timeout. Individual builds and model runs have tighter caps.
The watchdog uses sampled RSS and pidfd cleanup, not cgroup containment.
Raw inputs are dependencies of the frozen basis package; this study does
not regenerate or alter them. Results and packaging admission are recorded
separately from the numerical run.

## Remaining Work

Route the production candidate with the original toolchain environment,
clock and connectivity, then check final timing/resources and alternate
paired board runs with complete results. The preserved route attempt was
not started: its 40-GiB tree budget plus 16-GiB reserve exceeded available
memory. The future route wrapper also requires explicit toolchain-environment
validation; it does not source the original link shell automatically.

Only matched FPGA evidence can admit the candidate's hardware timing. A
production simulator candidate must then represent all confirmed scheduling
and completion behavior, replay legacy fixtures exactly and pass bounded
hardware checks without a fitted catch-all delay. Original A4 versus actual
adapter+K4 performance, strict resource matching, batch-to-convergence and
original-publication matching remain open. This sensitivity package does
not complete those goals.
