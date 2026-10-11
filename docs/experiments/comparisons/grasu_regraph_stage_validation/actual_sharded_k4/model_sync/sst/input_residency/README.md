# Initial Input Residency: Controlled FPGA Check

## Finding

The frozen host did not guarantee that every shard's initial inputs were
device-resident before compute. Its `enqueueWriteBuffer` calls and queue
completion were insufficient under this XRT implementation. A separate,
opt-in initial migration removes observable row-table transfers from the
compute window without changing the bitstream, model, full result or rounds.

**All 30 executions pass complete-result and round-geometry checks. No timing
coefficient was fitted. Original-A4 matching and exclusive-stage calibration
remain open.** This checkpoint does not replace any previous raw evidence.

Start with [residency.json](residency.json) for all numbers and claim limits,
[residency_raw_index.json](residency_raw_index.json) for identities, and
[raw_residency.tar.gz](raw_residency.tar.gz) for the portable evidence.

## What Was Actually Tested

- Warm weighted SSSP: identical old-graph converged state, eight updates,
  synchronous propagation through the same final convergence condition.
- The previously admitted original and optimized adapter bitstreams, four
  Little frontends, shared downstream, 150 MHz, U55C device 1. The optimized
  adapter has row prefetch and stop-after-last enabled.
- Fixed v4 model predictions from the preceding
  [six-row matrix](../empty_exit_matrix/README.md); no rerun, retuning or
  changing memory assumptions to follow the new FPGA measurements.
- CPU affinity 122,123; serial board lease and idle-board check; 8 GiB per
  process, 16 GiB reserve and 600-second timeout. All runs completed. Peak
  recorded process RSS is 1,409,296 KiB; summed process wall time is 359.24 s.
  This RSS is the maximum individual process, not a concurrent tree sum.

The preceding [nine-run affinity control](../dispatch_affinity/README.md)
found that allowing two, eight or 32 CPUs did not close the WK discrepancy.
It remains a useful negative control, not a discarded failed experiment.

## Why Residency Matters

The frozen-host OpenCL/HAL trace aligns uniquely with all 56 logged compute
kernel intervals. It contains **16 row-sized writes, totaling 145,939,200 B,
inside the compute window**. Each row table is `(1,140,149 + 1) * 8` bytes.
Each write has a dependency into its adapter invocation. The other two row
tables belong to shards already touched by the GraSU update phase. Earlier
host writes target the same BO addresses and banks, so this is not evidence
of BO relocation.

XRT 2.18.179 identifies branch 2024.2 and source hash
`3ade2e671e5ab463400813fc2846c57edf82bb10`; runtime libraries are hash-pinned.
In that version, writing a nonresident BO updates host memory but does not
necessarily migrate it or set residency. Kernel-argument migration can
subsequently perform the transfer. Explicit host-to-device migration does
establish residency. See the official
[device write/migrate implementation](https://raw.githubusercontent.com/Xilinx/XRT/2024.2/src/runtime_src/xocl/core/device.cpp)
and [enqueue migration implementation](https://raw.githubusercontent.com/Xilinx/XRT/2024.2/src/runtime_src/xocl/api/enqueue.cpp).

The intervention adds `GRASU_SHARDED_PREMIGRATE_INPUTS=1` to the production
SSSP/CC host. It is **default-off**, accepts only 0/1, and explicitly migrates
all ten initial input BOs per shard **before GraSU updates**, not afterward.
Moving host PMA copies after updates could overwrite device modifications.
The migration has a separate event and wall-time record outside compute.
This does not implement per-batch remigration or change HLS.

Do not call the earlier host write a first PCIe DMA or the later transfer a
"second DMA": the earlier call may only stage host memory. Transfer lifetimes
overlap and cannot be summed into an exclusive time penalty.

## WK Causal Control

Three rotating, unprofiled repetitions per arm; profiling is a separate tenth
run, not a sample in the medians. Same graph, optimized bitstream and output.

| Host / setting | Median compute span (ms) | Range (ms) | Separate initial migration (ms) |
| --- | ---: | ---: | ---: |
| Frozen host | 94.296 | 89.247--100.093 | Not explicitly requested |
| New host, option off | 96.933 | 91.891--96.950 | Not explicitly requested |
| New host, option on | 64.268 | 64.238--64.547 | 51.326 |

The separate profiled on-run spans 64.596 ms, also aligns all 56 kernel
intervals, and contains **zero compute-window `WRITE_BUFFER` transfers**.
Its initial migration takes 52.774 ms. This intervention supports the
initial-residency explanation for a substantial part of the WK mismatch;
it does not assign every previously observed gap to PCIe transfer time.

For WK the option migrates 180 BOs / 467,538,224 B. This work is not free.
Neither the compute-span decrease nor the model's closer agreement is a
setup-inclusive end-to-end speedup claim. Initial graph loading and later
resident-batch execution must be reported separately and symmetrically.

## Complete Six-Row Recheck

Three rotating, unprofiled repetitions of **every** original/optimized row
after explicit initial residency. FPGA spans run from first compute-kernel
start to last compute-kernel end, including any interior dispatch/wait gaps.
Predictions omit host dispatch/relaunch. Errors below are consequently
**nominal window differences**, not exclusive-stage calibration errors.

| Graph / adapter | Fixed predicted compute (ms) | Median FPGA span (ms) | Nominal signed difference | Initial migration median (ms) |
| --- | ---: | ---: | ---: | ---: |
| AU / optimized | 192.798 | 192.907 | -0.06% | 20.180 |
| AU / original | 2,076.570 | 2,044.190 | +1.58% | 20.710 |
| SU / optimized | 390.491 | 389.498 | +0.25% | 22.981 |
| SU / original | 3,429.049 | 3,376.124 | +1.57% | 23.533 |
| WK / optimized | 60.164 | 64.279 | -6.40% | 54.775 |
| WK / original | 5,740.279 | 5,644.913 | +1.69% | 54.682 |

The complete matrix is within 6.41% nominally, without a model adjustment.
This is bounded warm-SSSP aggregate-window evidence. Physical DRAM mapping,
exclusive stalls, other algorithms, unseen graphs and original-publication
performance are **not** admitted by it. Same-CU gaps and overlapping whole
`lksg` lifetimes cannot stand in for exclusive component counters.

## Reproduce And Review

Owners separate execution (`dispatch_trace.py`, `input_residency.py`,
`residency_matrix.py`), structured trace parsing (`runtime_trace.py`), raw
validation (`residency_validation.py`) and immutable packaging
(`residency_delivery.py`). All live in
`spine_cycle_sim/experiments/sharded_k4_stages/`. The archive contains source
snapshots, pre/post host source, the new executable/build provenance, all
logs/resources/traces, and one complete result per distinct output hash.
Large graphs, bitstreams and runtime libraries remain external hash-pinned
dependencies. Archived absolute paths describe the original machine; remap
them deliberately on another host rather than silently editing manifests.

From the repository root, each runner supports `--help`:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.dispatch_trace --help
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.input_residency --help
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.residency_matrix --help
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.residency_delivery --help
python3 -m unittest discover -s tests -p 'test_sharded_k4_*residency*.py'
python3 -m unittest discover -s tests -p 'test_sharded_k4_runtime_trace.py'
```

Recorded campaigns: `/data/chuxiao/experiments/sharded_k4_runtime_trace_20261011`
and `/data/chuxiao/experiments/sharded_k4_input_residency_20261011` (its
`control/` and `matrix/` children). Runners require fresh output paths and
refuse inherited intervention/profiling settings. The saved host build
manifest's `candidate_hls_host_not_yet_run` is a compile-time label; actual
run admission is established here by the complete result and raw-log gates.

Next is the matched **original four-Little A4 versus actual optimized
adapter+K4** comparison. The above "original" arm is our old adapter, **not
original ReGraph A4**. Matching algorithm/arithmetic, initial state, rounds,
resident timing boundary and resources remains mandatory; an aggregate
SSSP timing match cannot substitute for that comparison.
