# Direct CC FPGA Measurements

November 6, 2026. This is the direct board campaign using the existing
Spine CC streaming image. It does not wait for the independent routing-report
rebuild. Results and raw logs will be added when the running matrix finishes;
this launch record alone is not a complete eight-dataset result.

## Completed Pairs

The running campaign has completed these pairs. Ratios are G+R wall time
divided by Spine wall time; values above one favor Spine. Pending rows are
not estimated or filled from an older image.

| Dataset | Spine, ms | G+R, ms | G+R / Spine | Spine rounds | G+R steps |
| --- | ---: | ---: | ---: | ---: | ---: |
| AU | 4.731461 | 5.563717 | 1.1759 | 0 | 1 |
| SU | 3.451350 | 6.558909 | 1.9004 | 0 | 1 |
| WK | 12.632963 | 32.553868 | 2.5769 | 2 | 2 |
| SO | 37.319110 | 220.937809 | 5.9202 | 0 | 1 |
| PK | 5.227821 | 46.870413 | 8.9656 | 0 | 1 |
| LJ08 | 9.264784 | 246.582085 | 26.6150 | 0 | 1 |
| R19 | 10.381851 | 41.171681 | 3.9657 | 2 | 2 |

All seven pairs pass their final-state checks. LJ is running. This is a
CC-only update, not completion of Figures 7--11.

### Longer Preparation Limit

LJ exhausted the original 1,800-second process timeout during old-graph
convergence, before producing a measured batch sample. It was in its third
propagation round; no OOM or cgroup-limit event occurred. The subsequently
started LJ08 process was explicitly stopped during input loading, rather
than spending another preparation attempt under that same short limit.
Its `remaining/lj08/operator-stop.json` records this operator decision.
These attempts remain preserved; neither is a measured performance loss.

The two initially missing datasets were resumed serially under the separate service
`spine-cc-direct-long-startup-20261106-v1.service`, with
`--arm-timeout-seconds 7200` and output `long_startup/` beneath the base below.
This changes the process deadline, including unmeasured preparation, not the
batch timing boundary. The host, images, inputs, affinity, correctness checks,
single sample and zero-swap containment remain unchanged. Completed
datasets are not rerun. The runner's default remains 1,800 seconds.
The longer run was launched from simulator commit `e4da2406`.

Its LJ attempt failed at BOOTSTRAP with a zero workspace header and a stale
propagation result, before any batch timing. This followed the interrupted
original stream. Residual device state is suspected, not a confirmed ABI or
workload defect. While LJ08 was still loading input and the render node was
unopened, the board was successfully programmed with the existing G+R image
so that its next Spine load changes the programmed UUID. The operation and
observations are retained in `long_startup/device-recovery.json`. LJ08 then
completed both arms successfully. LJ is running in a separate attempt; no
failed sample is replaced by a number before that attempt completes.

The current LJ retry is running under
`spine-cc-direct-recovered-lj-48g-20261106-v1.service`, writing `recovered_lj_48g/`,
from clean simulator commit `8d055ba8`.
It allows up to 14,400 seconds for board/memory admission before either arm,
then the same 7,200-second process timeout per arm. The queue does not open
the board or allocate graph buffers until the existing pair releases its
lease and its full finite 48-GiB budget plus reserve fits. This is not a
parallel board run or a change to the measured interval.

### Large CPU Audit Capacity

The unchanged host checks the full graph on the CPU both before and after
the measured batch. On LJ08, retained maps for these exact checks exceeded
the original 30-GiB soft limit, then the 36-GiB soft limit. The owned service
was extended from max/high 32/30 to 40/36 and finally 48/46 GiB, each with a
matching atomic full-reservation update and the same 32-GiB effective live
reserve, pressure monitoring and zero swap. The extensions occurred before
batch packing and after final readback, respectively. They did not change
the measured interval. `long_startup/live-memory-budget.json` retains the
before/after settings, memory observations and reasons.

The completed LJ08 Spine arm reached 48,414,642,176 bytes (45.09 GiB) cgroup
peak. Soft-limit throttling was recorded; hard-limit and OOM counters were
zero. Thus this is not a claim of zero memory-pressure events. The final LJ
retry reserves 48/46 GiB up front. Its earlier 32-GiB and 40-GiB queues were
stopped before either arm started; their `operator-stop.json` records remain
under `recovered_lj/` and `recovered_lj_40g/`. No measured sample was discarded.

## Measurement

Both systems start with the old graph and converged labels resident. Each
applies the original eight logical undirected insertions (sixteen physical
records) and runs to the checked final state. The reported window starts at
host batch packing and ends after final readback. Initial old-graph loading
and convergence are outside that window. Use one sample per arm, no warmup
or repeated averaging. CPU affinity is 124,125 on card `0000:82:00.1`.

The seven-case Spine run uses `--hot balanced --mode partial --samples 1`.
SU, WK, R19, SO, PK, LJ and LJ08 run sequentially, with fresh Spine and G+R samples.
AU uses `--hot 0` for the new Spine measurement and the explicitly retained same-image
G+R sample from `cc-warm-au-source-bursts-resident-v8`. AU's G+R arm is not
silently described as a fresh measurement.

Final labels, graph updates and work checks remain required. The raw routed
bus-skew report is missing for the Spine image. That limits static timing
documentation; it does not prevent programming the existing xclbin or
reporting its actual, correctness-checked execution time. Do not relabel this
campaign as having complete routed timing evidence. Driver-reported clocks
are saved per arm.

## Artifacts And Live Output

The run host's base directory is:

```text
/data/chuxiao/checks/source-retention-repair-20261104/cc-stream-direct-board-20261106-v1
```

- `image/spine_partitioned_split_e2e.engine-4-1-2-2-1.hw.xclbin`: Spine image.
- `AU/results.json` and `AU/spine_cc.stdout.txt`: completed AU Spine sample.
- `remaining/matrix.json`: all seven subsequent dataset statuses and results.
- `remaining/<dataset>/pair.json`: each completed pair's wall times and ratio.
- `remaining/<dataset>/{spine,gr}.stdout.txt`: raw program output.

The simulator runner is
`spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.cc_direct_matrix`.
The original service `spine-cc-direct-matrix-20261106-v1.service` and the
longer-startup service are terminal; only the final LJ retry is active. This is a
board-only runner: it changes no HLS, numerical model, input graph or paper.
Finite process limits and live memory protection remain active.

From a full simulator checkout with the indexed files available:

```sh
runner=spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.cc_direct_matrix
checks=/data/chuxiao/checks/source-retention-repair-20261104
base="$checks/cc-stream-direct-board-20261106-v1"
systemd-run --user --wait --pipe --unit=cc-direct-fresh \
  -p MemoryMax=48G -p MemoryHigh=46G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p KillMode=control-group -p RuntimeMaxSec=21600 \
  --working-directory="$PWD" \
  /usr/bin/python3 -m "$runner" \
  --previous /data/chuxiao/checks/grasu-replicated-host-singlepass-20261026-v1/matrix \
  --spine-host "$checks/spine-cc-stream-admit-2315cae-offline-host-v1/host_cc_repair" \
  --spine-image "$base/image/spine_partitioned_split_e2e.engine-4-1-2-2-1.hw.xclbin" \
  --gr-host "$checks/gr-active-min-wall-host-v1/connected_components/sharded_k4_cc_native_host" \
  --gr-image "$checks/seele-return-v1-cc-banked-source-bursts-final/returned/route/candidate.hw.xclbin" \
  --inputs SU "$checks/spine-cc-warm-balanced-small-inputs-v1/su/inputs.json" \
  --inputs WK "$checks/spine-cc-warm-balanced-small-inputs-v1/wk/inputs.json" \
  --inputs R19 "$checks/spine-cc-warm-balanced-r19-inputs-v1/r19/inputs.json" \
  --inputs SO "$checks/spine-cc-warm-balanced-large-inputs-v1/so/inputs.json" \
  --inputs PK "$checks/spine-cc-warm-balanced-large-inputs-v1/pk/inputs.json" \
  --inputs LJ "$checks/spine-cc-warm-balanced-large-inputs-v1/lj/inputs.json" \
  --inputs LJ08 "$checks/spine-cc-warm-balanced-large-inputs-v1/lj08/inputs.json" \
  --arm-timeout-seconds 7200 \
  --memory-gib 48 \
  --output /path/to/fresh-cc-measurements
```

After all attempts are terminal, export the original matrix together with
the ordered retries. The exporter only permits replacement of failed attempts,
requires unchanged artifacts and inputs, and retains all original records.

```sh
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.cc_direct_export \
  --matrix "$base/remaining/matrix.json" \
  --resume "$base/long_startup/matrix.json" \
  --resume "$base/recovered_lj/matrix.json" \
  --resume "$base/recovered_lj_40g/matrix.json" \
  --resume "$base/recovered_lj_48g/matrix.json" \
  --au "$base/AU/results.json" \
  --au-gr "$checks/cc-warm-au-source-bursts-resident-v8/results.json" \
  --output /path/to/fresh-cc-data
```

To render the combined three-algorithm preview after export, use the existing
Python GraphyFlow/TX Typewriter renderer. The overlay replaces only pending
CC slots; it neither rewrites the frozen sixteen measured SSSP/ResPR pairs
nor turns the missing CC routing report into timing-closure evidence.

```sh
pkg=docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105
python3 "$pkg/render_current.py" \
  --resident-checkpoint "$pkg/current_fpga/resident_checkpoint_v3/fig7_resident_checkpoint.csv" \
  --cc-direct /path/to/fresh-cc-data/fig7_cc.csv \
  --output /path/to/fresh-figures
```
