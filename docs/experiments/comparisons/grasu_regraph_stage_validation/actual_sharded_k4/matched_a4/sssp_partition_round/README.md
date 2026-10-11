# Four-Partition SSSP Resident-Round Diagnostic

## Finding

The frozen actual-K4 composition is **slower than original-style A4 in this
fixed-model control**. Six complete runs pass state, work and traffic checks.
This is a negative simulator finding, not an FPGA slowdown measurement or
an original-paper reproduction. The earlier 650-vertex single-partition
result does not generalize to this input.

| Scenario | Mock latency | A4 cycles | K4 model cycles | K4 / A4 |
| --- | ---: | ---: | ---: | ---: |
| Cold, one round | 64 | 668,278 | 23,478,378 | 35.133 |
| Warm update, one round | 64 | 668,278 | 23,478,378 | 35.133 |
| Warm update, one round | 128 | 1,292,225 | 36,980,821 | 28.618 |

Each row also runs with reversed component registration. Both orders must
match exactly in cycles, counters and all output words. All seven padded
state replicas (four A4, three K4), each 262,144 words, match the synchronous
oracle. The warm/cold output state differs despite identical scan-cycle
counts; both have three active output vertices.

## Fixed Scope

- Source: pinned `amazon-2008.mtx`; SHA-256
  `60b383901873b49883d0c67d8b524244ada1977719d25c834014b75238f3a815`.
  Select unique directed edges induced by original external IDs 1--258,048;
  subtract one, without compacting internal holes, degree caps or added edges.
  The last two IDs are unused, so the author's loader infers 258,046 vertices.
- The slice has 1,450,899 edges. The unchanged author probe applies DBG and
  creates sixteen dense A4 tasks. Destination shards contain 848,130,
  370,883, 170,898 and 60,988 edges. All four K4 workers have assigned work;
  independent runtime-per-worker counters are not serialized here.
- Weights are a declared local positive 12-bit overlay, not published SSSP
  weights. The warm arm begins with old converged distances; the update
  decreases original source 0's outgoing weights by 16 and reactivates it.
  Both paths consume the same graph, state and active source.
- Exactly **one synchronous resident round**, not propagation to convergence.
  Timing starts at the first component tick and ends after every state-write
  acknowledgement. Preparation, GraSU update, DMA and host orchestration
  are outside this diagnostic window.
- Fixed MockMemoryBackend, not DRAMSim3 or board measurements: 150 MHz,
  32 channels, one issue per channel per cycle, 32 outstanding and response
  credits per channel. Latencies 64/128 are sensitivity controls, not fitted
  parameters. The numerical executor/profile are unchanged from the
  [preceding admitted checkpoint](../sssp_real_round/README.md).

The mock service is common, but resources are **not strictly matched**:
A4 has thirteen logical AXI masters, four state replicas and shared read/write
credits; K4 has nine masters, three replicas plus status and independent
read/write credits. Layout, scheduling and merger organization also differ.
Do not label the ratio as isolated adapter overhead or an admitted same-resource
FPGA speedup.

## Conserved Work And Diagnosis

| Payload/work quantity, invariant across the matrix | A4 | K4 model |
| --- | ---: | ---: |
| Read bytes | 17,446,400 | 101,741,312 |
| Write bytes | 4,194,304 | 3,145,732 |
| Logical edges | 1,450,899 | 1,450,899 |
| Physical edge slots | 1,451,712 | 7,609,792 |
| Dummy slots | 813 | 6,158,893 |

K4 accounts for four extent reads, 1,032,172 row reads, 475,612 segment
reads, 65,536 source lines and 16,384 old-state reads, each 64 bytes.
Primary and two source-state replicas plus four-byte status explain every
write byte. Requests, completions, beats, valid/dummy work, active count,
writer guards and drained resources are checked; no state is accepted by
hash sampling alone.

`layout_audit` independently reconstructs the PMA work from captured CSR.
It includes the routed source-0 dummy reservation in the two shards whose
source 0 has no live edges. The reconstruction must equal runtime row,
segment, live-edge and dummy-edge counters.

| Shard / assigned worker | Live edges | Visited source rows | Empty visited rows |
| --- | ---: | ---: | ---: |
| 0 | 848,130 | 258,046 | 78,538 |
| 1 | 370,883 | 258,045 | 102,119 |
| 2 | 170,898 | 258,037 | 159,126 |
| 3 | 60,988 | 258,038 | 216,771 |

In the frozen model, each visited row incurs six serial control cycles and
each empty visited row retires a 73-cycle helper-exit pipeline. Shard 3 alone
therefore has a **17,372,511-cycle serial-control lower bound**, before its
other work. This explains why the edge-light shard is not necessarily cheap.
Rows are prefetched in groups of eight, but each row is still a distinct
64-byte request; this is not eight row values served by one cached line.

These facts identify remaining directory, empty-row and padding costs.
They are not exclusive runtime-stall measurements, and they do not prove
which change will recover a particular FPGA speedup. Streaming and destination
sharding do not by themselves eliminate these costs.

## Preserved Attempts

- `run-v1`: exact 262,144-vertex extent violates original A4 source-lookahead
  allocation. Rejected before timing; the guard was not relaxed.
- `run-v2`: selected upper bound was incorrectly required to equal maximum
  used ID. Rejected during preparation; loader-compatible extent inference
  was then made explicit.
- `run-v3`: A4 passes; K4 exhausts the declared ten-million-cycle simulation
  budget. This is **cycle-budget exhaustion, not a wall timeout or proof of
  deadlock**. Partial states/diagnostics are retained, not admitted as a pair.
- `run-v4`: all six cases pass with a declared 100-million-cycle cap. Its
  exact Python execution bytes were frozen before strengthening delivery.
- `run-v5`: command and process-cleanup hardening; exactly the same complete
  states/cycles/counters as v4. Its exact Python bytes are also preserved.
- `run-v6`: adds observed-cycle budget and cleanup-error gates, plus lossless
  archive compression. Numerical code and model remain unchanged. Delivery
  requires exact numerical equality to both previous successful runs.

The historical v1--v3 Python bytes were not snapshotted and cannot be
retroactively recovered: their recorded hashes and raw outputs are retained,
but no byte-reproducibility claim is made for those attempts.

## Handoff And Reproduction

The [results](evidence/results.json), [verification manifest](evidence/verification.json),
[current raw archive](evidence/raw_sssp_partition_round.tar.xz) and
[prior-attempt transport manifest](evidence/prior_attempts_parts/transport.json)
form one handoff. The prior archive exceeds GitHub's per-file limit, so its
original bytes are committed as three lossless, hash-checked chunks. The
large local archive is ignored, not substituted with reduced evidence.
Archives include complete inputs, captured author layouts, all complete
states, raw stdout/stderr, resource records, and current execution Python.
The prior archive also includes v4/v5 exact source snapshots. Numerical
sources/executables, compiler/cache and author tools remain hash-indexed by
the preceding checkpoint; they are not silently rebuilt or substituted.

Reassemble the prior archive to a fresh output from the repository root:

```bash
python3 -m spine_cycle_sim.experiments.artifact_transport join \
  --directory docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/matched_a4/sssp_partition_round/evidence/prior_attempts_parts \
  --output /tmp/prior_attempts.tar.xz
```

Run from the repository root with the recorded dependencies present:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.study \
  --output results/sssp-four-partition-reproduction \
  --source /data/feiyang/ReGraph/dataset/amazon-2008.mtx \
  --baseline /data/chuxiao/experiments/a4_actual_sssp_real_round_20261011/run-v3/results.json
```

Each child has an 8-GiB address-space cap and 180-second timeout. The outer
watchdog has an 8-GiB sampled tree-RSS budget, 16-GiB live-memory reserve and
1,500-second timeout. Linux pidfds track observed descendants across nested
sessions. This is not cgroup containment: a child that forks/reparents between
samples can escape observation. Nested-session timeout and snapshot-failure
negative tests check the implemented cleanup behavior.

Final regression checks pass 299 Python tests (original-ReGraph, sharded-K4
and repository structure) and all 28 C++ tests in the frozen executor build.
The Python checks use a three-GiB sampled tree budget and preserve the
16-GiB live-memory reserve. Their logs and the CTest log are indexed in
`evidence/checks/verification.json`. No numerical C++ source or default SST
plugin changed in this checkpoint.

Package to a fresh directory with `sssp_partition_round.delivery --run RUN
--destination DESTINATION`. Repeat `--prior-attempt PATH` for preserved
attempts. Delivery rechecks raw command arrays, execution declarations,
budgets, source/executable identities, regenerated inputs, every saved state,
traffic, registration-order invariance and latency sensitivity.

## Next Gate

Check the directory/empty-row path against bounded actual-HLS schedules and
matched board timings. Optimize the production HLS where confirmed, then
introduce an explicitly versioned simulator candidate with old/default
regressions and new correctness/traffic checks. A fixed-model slowdown alone
does not calibrate A4, prove PMA inherently slow, close publication matching,
or complete the original performance-validation objective.
The subsequent [empty-helper C/RTL control](../../adapter_optimization/empty_segment/README.md)
now supplies a concrete production-HLS candidate; it does not silently retime
or overwrite this frozen diagnostic.
