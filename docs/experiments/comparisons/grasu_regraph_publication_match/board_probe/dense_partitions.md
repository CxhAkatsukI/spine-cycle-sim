# Original ReGraph Dense-Partition Control

## Answer

`numD=3` works on the existing original-source 11-Little/3-Big U55C bitstream.
No HLS edit, synthesis, routing, simulator change or paper edit was required.
The author's camera-ready Amazon command passes `3`; our previous control
explicitly selected `1`. The author's scheduler runs unchanged in both cases.

On Amazon (735,324 vertices; 5,158,388 logical directed edges), the warmed
median device-event envelope changes from **4.648 to 3.399 ms**, and throughput
from **1.110 to 1.518 GTEPS**, a **1.367x** increase. Both configurations pass
all ten declared executions, including independent CSR-oracle equality,
14 output replicas, publication padding, guards and immutable input checks.

| Dense partitions (`numD`) | First execution, ms | Warm baseline median, ms | Warm baseline GTEPS | Warm author-order median, ms | Warm author-order GTEPS |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 9.623 | 4.648 | 1.110 | 4.629 | 1.114 |
| 3 | 6.621 | 3.399 | 1.518 | 3.319 | 1.554 |

Warm baseline event ranges over three repeats are 4.603--4.651 ms and
3.337--3.408 ms. Full resident host-wall medians are 4.691 and 3.437 ms.
The cold samples are each process's first execution, not a median.

## Meaning And Boundary

`numD` counts 65,536-destination partitions assigned to Little pipelines;
it is **not** a Big kernel count. The remaining destination partitions are
merged in groups of eight and assigned to Big pipelines. Both runs use
11 Little and 3 Big kernels, the same physical board and 150-MHz bitstream.
The geometry changes from 17 tasks (11 Little, 6 Big) to 39 tasks
(33 Little, 6 Big). Big still executes in both configurations.

This is one static fixed-point PR superstep from the same resident initial
state, **not convergence, dynamic-update speedup or latest K4 adapter+R**.
The numerator is logical edges. Time spans the earliest CU start through
the latest CU end; overlapping lifetimes are not summed. Preparation,
initial DMA and verification readback are outside that device window.
Host wall also includes argument binding, enqueue and completion.

Each configuration runs a cold baseline, then three interleaved repetitions
of baseline, author enqueue order, and a prebound negative control. The latter
creates fresh kernel handles per task: its host-wall medians are 1,415 and
3,287 ms, even though its device envelopes are 4.702 and 3.412 ms. It is **not**
claimed as a host optimization. No samples or host times are subtracted.

The longest Big lane's summed CU lifetimes decrease from approximately
4.50 ms to 3.23 ms; the longest Little lane increases from about 0.55 ms to
1.40 ms. This is consistent with moving work from Big to Little, but CU
lifetimes include waiting and do not isolate internal compute stages.

## Integrity And Limits

The original host-layout probe reruns the author's reordering and scheduling
with seed 73. Graph SHA256, vertex mapping, CSR, initial values, degrees and
logical oracle output match between configurations. The regenerated `numD=1`
input is byte-identical to the frozen control. Both have 5,165,928 physical
edges, including 7,540 dummy entries; neither drops logical work.

Only a **staged copy** of the validator is patched to admit `dense==1 ||
dense==3`, retaining its capacity, task-mapping, arithmetic, oracle and guard
checks. Frozen sources and inputs remain unchanged. Publication extents are
1,114,112 and 1,245,184 vertices, respectively: buffers cover the complete
publication range and guards, rather than using an undersized aligned array.
Both launches produce the same host binary hash and use the same xclbin hash.

This is a meaningful correction to the earlier paper comparison, not a
completed publication match. Camera-ready Table IV AM PR reports 3.744 GTEPS
(System) and 4.224 GTEPS (Best). Their raw ratios to the new baseline are
2.47x and 2.78x, **not controlled reproduction errors**. Board/toolchain/clock,
selected topology, iteration and exact input-state/timer equivalence still
need checking. A frequency-scaled estimate is not a measured result. The
prior approximately sevenfold comparison combined a cold launch with a
different dense-partition setting and must not be treated as the steady-state
gap for the author's example.

Source: [ReGraph camera-ready, Appendix and Table IV](https://soldierchen.github.io/assets/pdf/regraph.pdf).
The Appendix command is `./host_graph_fpga_pr xclbin_hw_pr/*.xclbin
./dataset/amazon-2008.mtx 3`. It is an artifact example, not proof that Table IV
uses this exact topology and parameter.

## Evidence And Reproduction

Start with [dense_results.json](dense_results.json). Raw data, staged sources,
commands, manifests, offline expectations and board output replicas are under
`/data/chuxiao/checks/original-r-numd-20261025-v1/`. Failed historical controls
and earlier reports have not been overwritten.

Code is in the existing [board-probe package](../../../../../spine_cycle_sim/experiments/publication_board_probe/):
`dense_inputs.py` prepares and checks inputs; `dense_admission.patch` describes
the sole validator change; `launch.py` and unchanged `launch_control.cpp`
execute; `dense_analysis.py` validates the complete matrix and packages it.

From the simulator worktree root, first run `dense_inputs` with a **new** output
directory. Subprocess commands are saved alongside their logs. Run each board
command sequentially, using the same bounded systemd resource policy above:

```bash
export XILINX_XRT=/opt/xilinx/xrt
frozen=/home/chuxiao/spine-cycle-sim/spine-cycle-sim-regraph-a4-board
raw=/data/chuxiao/checks/NEW-numd-study
source=/data/chuxiao/experiments/baseline_hardware_validation_20261015
python3 -m spine_cycle_sim.experiments.publication_board_probe.dense_inputs \
  --frozen "$frozen" --manifest "$source/original-r-board-supervisor-v4/manifest.json" \
  --probe "$PWD/results/upstream_stage_controls/original_host_inputs_final_v3/original_example/probe" \
  --graph "$source/original-r-source-route-v6/build/source/dataset/amazon-2008.mtx" \
  --output "$raw"
# First run with numd1/board_numd1, then numd3/board_numd3:
PYTHONPATH="$frozen" python3 spine_cycle_sim/experiments/publication_board_probe/launch.py \
  --manifest "$raw/numd3/manifest.json" --frozen "$frozen" \
  --headers "$raw/original_regraph/hardware" \
  --device 1 --bdf 0000:c1:00.1 --output "$raw/board_numd3"
python3 -m spine_cycle_sim.experiments.publication_board_probe.dense_analysis \
  --directory "$raw" --output "$raw/summary.json"
```

All three services use MemoryMax 8 GiB, MemoryHigh 7 GiB, no swap, bounded
deadlines and serial board access. Available memory was about 80 GiB before
the test; board launch requires at least 24 GiB. Peak RSS/accounted memory was
494 MiB for preparation, 436 MiB for numD=1 and 429 MiB for numD=3. No new
simulator campaign, full Python suite or routing was performed.

Validation: 37 focused Python tests pass, as does the staged C++ board-model
test. Document-layout, generated-catalog and whitespace checks pass.
