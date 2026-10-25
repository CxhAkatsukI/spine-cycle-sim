# Original ReGraph Launch Diagnosis

## Finding

The initial roughly sevenfold publication-rate gap was not a controlled
reproduction error. A fresh same-bitstream experiment confirms that the first
resident execution is almost twice as slow as subsequent executions. This is
an observed launch/runtime effect, not a simulator coefficient adjustment.
**Publication matching remains unestablished**, with a substantial warm gap
still requiring investigation.

The original-R port in this experiment has no PMA adapter. Its results cannot
be attributed to PMA bridging or substituted for the latest sharded K4 path.
No production HLS, simulator timing coefficient, paper or figure was changed.

## Controlled Measurements

All rows use the same original-source 11 Little + 3 Big bitstream, Amazon
input, initial property buffers, oracle and HBM mapping on U55C
`0000:c1:00.1`. They repeat the same resident static PR superstep (`arg=0`),
not successive convergence iterations. The reference inputs are immutable.
Every execution checks all output replicas, padding, guards and immutable
inputs; output hashes also match the independently pinned manifest oracle.

| Mode | Samples | Device event envelope | Full resident host wall | Throughput |
| --- | --- | --- | --- | --- |
| Baseline, first execution | 1 | 9.012 ms | 22.404 ms | 0.572 GTEPS |
| Baseline, warm | 3, median | 4.693 ms | 4.741 ms | 1.099 GTEPS |
| Author enqueue order and timer, warm | 3, median | 4.687 ms | 4.726 ms | 1.101 GTEPS |
| New per-task kernel handles, prebound arguments, warm | 3, median | 4.840 ms | 1400.371 ms | 1.066 GTEPS |

The complete ten-execution matrix is retained in
[launch_results.json](launch_results.json), with raw report, host, source,
bitstream, manifest and runtime identities. Initial DMA and final correctness
readback are outside these resident windows. Device time is an overlap-aware
envelope, never a sum of concurrent CU durations. Host wall includes argument
binding and kernel-handle preparation where performed.

Warm baseline event times are 4.693, 4.683 and 5.187 ms; the last observation is
retained, not discarded. An earlier successful seven-execution diagnostic
also measured a 4.691-ms warm baseline median in a separate process. The
initial 12-run R probe used independent processes and therefore repeatedly
measured first executions. Its approximately 0.557-GTEPS result remains valid
for that cold boundary, not for warmed throughput.

## All-Little Follow-Up: Four Little, Zero Big

A separate board run uses the existing original-source A4 bitstream, not
the mixed bitstream with work omitted. All twelve destination partitions
run on four Little lanes: 48 tasks, zero Big tasks, 735,324 logical vertices,
5,158,388 logical edges and 5,165,928 physical edges including padding.
The graph, author-initial binding and logical oracle match the mixed-path
controls. This remains one resident static PR superstep, not convergence.
The board is U55C `0000:c1:00.1` at 150 MHz, with affinity 124,125.

| A4 launch mode | Samples | Device event envelope | Full resident host wall | Throughput |
| --- | --- | --- | --- | --- |
| Baseline, first execution | 1 | 9.977 ms | 12.774 ms | 0.517 GTEPS |
| Baseline, warm | 3, median | 5.480 ms | 5.509 ms | 0.941 GTEPS |
| Author enqueue order, warm | 3, median | 5.385 ms | 5.405 ms | 0.958 GTEPS |
| New per-task handles, warm negative control | 3, median | 5.935 ms | 1235.114 ms | 0.869 GTEPS |

Warm baseline repetitions are 5.545, 5.480 and 5.400 ms. Throughput uses
logical edges divided by the complete, overlap-aware device event envelope;
initial DMA and final verification readback are excluded. Author-order
post-enqueue wait is separately recorded (5.262 ms median), not substituted
for that envelope. All ten executions pass the independent oracle, all four
output replicas, padding, guards and immutable-input checks.

**Removing Big is functional, but this measurement does not reproduce the
paper's all-Little result.** Four Little lanes are not fourteen. Nor does
comparison with the separate 11L3B control isolate Big's effect: both lane
count and task partitioning differ. No linear extrapolation to fourteen
Little lanes or to another frequency is claimed. This run also contains
no PMA adapter and does not measure the latest sharded K4 path.

Raw evidence is
`/data/chuxiao/checks/original-r-a4-big0-warm-20261024-v1/results.json`, SHA-256
`930b727f4904dc913acacdc06e4cb797d2bfc8eac6822bfa09f042ce04e66bee`.
It pins the manifest, compiled host, frozen helpers, runtime and bitstream
(`b19b89545306460298c080550860e8836d8e5beb71cf161d0eacee2aec60436e`).
Reproduce with the guarded command below, replacing `--manifest` with
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/a4-board-supervisor-v3/manifest.json`
and choosing a fresh output directory and service unit. No new routing or
device-source changes were needed. The service completed in 17.445 seconds
with a 313.4 MiB reported peak under the same 8 GiB cap and memory reserve.

## What The Timeline Establishes

1. **First-execution effects are material.** First-wave gather/scatter starts
   span 4.007 ms on the first run, versus a 0.102-ms warm baseline median.
   Full device time falls from 9.012 to 4.693 ms without changing hardware,
   arithmetic, graph or banks. This isolates an execution-history effect; it
   does not uniquely identify one XRT function or internal hardware stall.
2. **The original timer is narrower, but not the remaining explanation.**
   The author host starts its timer after enqueueing all kernels. Reproducing
   its order without an explicit pre-wait flush gives a 4.550-ms median
   post-enqueue wait versus a 4.687-ms full event envelope: about 3% shorter.
   The public host source proves that timer location, not that every published
   measurement used exactly this revision. Our E2E boundary is not shortened.
3. **The warm critical path runs through the Big lanes.** Each Big lane runs
   two tasks sequentially. The median longest sum on one Big lane is 4.562 ms,
   compared with the 4.693-ms total. The median longest Little event is
   0.562 ms. These are CU lifetimes including stream, memory and merger waits;
   they are not internal compute-stage counters or proof of a particular AXI
   bottleneck. Concurrent lanes are not added together.
4. **Prebinding is not a demonstrated fix.** Creating separate task handles
   changes neither the bitstream nor graph but does not improve device time
   and adds about 1.4 seconds to host wall. This negative result is included.

## Publication And Configuration Audit

The [17-page camera-ready](https://soldierchen.github.io/assets/pdf/regraph.pdf)
must be distinguished from the local 13-page arXiv preprint. Camera-ready
Section VII-C explicitly normalizes Fig. 10 to 210 MHz. Table IV reports AM PR
at 3.744 GTEPS for System and 4.224 GTEPS for Best; Table V is preprocessing.
Earlier notes saying otherwise were incorrect and are superseded here.

The current 1.099-GTEPS warm result is numerically 3.41 times below System and
3.84 times below Best. **Those are still unmatched rate ratios, not controlled
reproduction errors.** Our bitstream uses U55C, 150 MHz, Vitis 2024.1 and XRT
2.18.179; the paper uses U280 and Vitis 2020.2 with the frequency conventions
above. Multiplying our throughput by a clock ratio is not a measurement.

Our pinned input uses one dense partition and two sparse groups, with 17
gather/scatter tasks. The camera-ready artifact's 11L3B Amazon invocation
uses three dense partitions. That example is not necessarily the paper's
graph-optimal configuration, but it establishes that our input partitioning
is not identical even to that example. Existing input generation already
performs degree-based grouping and a seeded within-group reorder; this is
not evidence that DBG is missing. Exact grouping, task balance and source
revision equivalence remain to be established.

The inspected mapping distributes edge/state arrays over HBM banks; no
all-ports-on-one-bank mistake was found. The runtime gate found calibrated
memory and an idle board before execution. Neither finding proves that all
memory traffic runs at its intended bandwidth. No measured evidence yet
attributes the remaining gap to board capability, thermal throttling or PMA.

## GraSU Is A Separate Open Problem

The G-only probe remains 2.841 Mupdates/s, versus the paper's AU 190.77
Mupdates/s under different batch, PE, platform and timing conditions. Its
latest build does use the complete URAM cache. Eight shards run serially;
one 976-update shard still takes 4.686 ms, and CU starts are staggered by
milliseconds. This establishes a large fixed-cost floor, not its unique
cause. No new warm-versus-cold G control is supplied by this R experiment.
Neither G nor the latest adapter+R has passed a publication-match gate.

## Next Discriminating Controls

- Generate independent-oracle inputs for source-prescribed dense/sparse
  partition settings on the same original-R bitstream. Compare all declared
  settings and task distributions, not just the fastest observed row.
- Report cold and warm results separately with full resident wall, device
  envelope and author wait window. Do not replace one boundary with another.
- Inspect the Big kernel synthesis schedules and memory/stream structure
  against the source before assigning finer causes. Internal stall attribution
  may require additional counters; CU lifetime alone cannot provide it.
- For G, repeat resident update timing with a declared valid update sequence
  and the original temporal/PE configuration. Repeated duplicate insertions
  are not a valid warm throughput control.

## Reproduce And Verify

Code owners are
[launch_control.cpp](../../../../../spine_cycle_sim/experiments/publication_board_probe/launch_control.cpp)
for the host control,
[launch.py](../../../../../spine_cycle_sim/experiments/publication_board_probe/launch.py)
for guarded execution, and
[launch_analysis.py](../../../../../spine_cycle_sim/experiments/publication_board_probe/launch_analysis.py)
for validation and packaging. Frozen oracle/device helpers come from commit
`535f8e8249e52a53142371c5d218e7621412eb23` of the original-R validation worktree.

The accepted raw run is
`/data/chuxiao/checks/publication-board-launch-20261025-v3/results.json`.
The `v2` sibling is a successful earlier diagnostic. The `v1` gated-launch
experiment was stopped without a completed oracle matrix and is not admitted.
Its failure is preserved, not recast as a performance result.

Confirm device id/BDF, idle state, available CPUs and at least 24 GiB available
memory first. Use a fresh output directory and service unit for every run:

```bash
systemd-run --user --wait --collect --unit=original-r-launch-NEW \
  -p MemoryMax=8G -p MemoryHigh=7G -p MemorySwapMax=0 -p RuntimeMaxSec=360 \
  --setenv=XILINX_XRT=/opt/xilinx/xrt \
  --setenv=PYTHONPATH=/home/chuxiao/spine-cycle-sim/spine-cycle-sim-regraph-a4-board \
  /usr/bin/python3 \
  /home/chuxiao/spine-cycle-sim/spine-cycle-sim-sharded-k4-v3/spine_cycle_sim/experiments/publication_board_probe/launch.py \
  --manifest /data/chuxiao/experiments/baseline_hardware_validation_20261015/original-r-board-supervisor-v4/manifest.json \
  --frozen /home/chuxiao/spine-cycle-sim/spine-cycle-sim-regraph-a4-board \
  --device 1 --bdf 0000:c1:00.1 \
  --output /data/chuxiao/checks/publication-board-launch-NEW

python3 -m spine_cycle_sim.experiments.publication_board_probe.launch_analysis \
  --raw /data/chuxiao/checks/publication-board-launch-NEW/results.json \
  --output /data/chuxiao/checks/publication-board-launch-NEW/summary.json
```

The accepted service completed in 13.024 seconds with a reported peak of
422.3 MiB. No new routing or simulator campaign was run. Focused tests cover
input semantics, timing conservation, complete repetition matrices, oracle
admission and median-not-best reporting. All 33 focused tests and the document,
catalog and whitespace checks passed:

```bash
python3 -m unittest tests.test_publication_board_probe tests.test_publication_match tests.test_repository_structure
python3 scripts/audit_repository_structure.py --check-docs
python3 scripts/audit_repository_structure.py --check-catalogs
git diff --check
```

The full Python suite and new simulator/HLS builds were not run.
