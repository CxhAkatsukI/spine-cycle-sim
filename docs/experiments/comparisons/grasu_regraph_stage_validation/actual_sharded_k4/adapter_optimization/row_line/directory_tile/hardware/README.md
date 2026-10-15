# Memory-Contained SSSP Routing

## Scope

Route one complete U55C sharded-K4 weighted-SSSP design with four instances
of the admitted 1024-row / 256-line-bank adapter. The other ten XOs,
HBM/stream connectivity and 150-MHz clock are preserved from the frozen
production design. This does not replace existing bitstreams, the production
simulator, paper figures, or FPGA performance conclusions.

The candidate XO SHA-256 is
`5dda403d8d07956f0a9f94211faeaa0e976bdc11d9f91863a2fe8da9a5e5ea5e`.
Preparation independently rechecks its complete synthetic AXI RTL, HLS
schedule/resources, integration sources, complete external ABI and padded
host evidence. Eleven XOs are copied and hashed into the fresh attempt;
only the adapter changes. A passing link still needs routed timing checks
and matched board correctness/performance tests before promotion.

## Safety Policy

| Guard | Policy |
| --- | --- |
| Start condition | Route budget + 24 GiB reserve + declared concurrent budgets, eight consecutive 2-second samples |
| Other builds | With `--allow-bounded-builds`, admit finite zero-swap compiler cgroups when all budgets fit; legacy attempts remain serial |
| Whole-service hard limit | cgroup v2 `memory.max = 40 GiB` |
| Reclaim/throttle threshold | `memory.high = 36 GiB` |
| Swap and OOM | No swap; group OOM kill; never increase limits automatically |
| Live system reserve | Stop our process tree below 24 GiB MemAvailable |
| Additional watchdog | 40-GiB sampled process-tree RSS limit, 2-second polling |
| Parallelism | Two synthesis and two implementation jobs; one route only |
| Time bounds | Queue at most 24 hours; link at most 6 hours |
| Temporary output | Fresh directory under `/data`, not the crowded `/tmp` tmpfs |

The supervisor verifies actual kernel cgroup files before waiting and again
before admission. A per-user lock excludes another invocation of this
supervisor. Limits cover all descendant processes, including detached worker
process groups. This limits our job, not other users' allocations: the live
reserve is sampled protection, not a guarantee against unrelated system OOM.
No other user's jobs, swap, ZFS ARC settings or system caches are changed.

For concurrent compilation, freeze `--allow-bounded-builds` during preparation.
The admission reader groups Vivado/Vitis HLS/v++/vpl processes by their bounded
cgroup ancestor and reserves the full hard limit once per group. Unbounded
or unverifiable competitors are not admitted. Add
`--background-memory-gib N` for concurrent non-FPGA workloads; this reservation
is additional to the 24-GiB system reserve. For the new search/R campaign,
8 GiB search + 6 GiB R + 40 GiB routing + 24 GiB reserve requires 78 GiB
available. MemAvailable already reflects current allocations; reserving full
limits is deliberately conservative. All live safety guards remain active.

## Current Attempt

The fresh October 15 attempt and replacement of the serial queue are tracked
in the [hardware-validation campaign](../../../../../evaluation_impact/hardware_validation/README.md).
The following October 12 observations are retained historical launch details.

Raw root:
`/data/chuxiao/experiments/sharded_k4_directory_bank_hw_20261012/attempt-v2`.
The systemd user service is
`spine-sharded-k4-bank-sssp-20261012-v2.service`.

This is a monitored queued build, **not a completed route**. Consult
`execution.json` for admission/routing status and `route.progress.json` once
the link starts. At preparation, the node had about 54 GiB available, below
the declared start threshold. The service will wait without launching Vivado
and stop after 24 hours if the threshold never becomes available.

`attempt-v1` is retained as a successful prerequisite/preflight preparation
that was never launched. A supervisor correction after freezing that attempt
required a fresh preparation; its manifest is not rewritten.

The initial service check confirmed `active/running`, 40/36-GiB hard/high
limits, zero swap, group OOM policy and `KillMode=control-group`.
`execution.json` reported `QUEUED_WAITING_FOR_SAFE_MEMORY`, 54.8 GiB
available, no other compiler jobs and `route_started=false`. These are
launch-time observations, not a continuously updated completion claim.

```bash
systemctl --user status spine-sharded-k4-bank-sssp-20261012-v2.service
systemctl --user show spine-sharded-k4-bank-sssp-20261012-v2.service \
  -p Result -p MemoryCurrent -p MemoryPeak -p MemoryMax -p MemoryHigh

# Stop only our queued/running build and all its descendants.
systemctl --user stop spine-sharded-k4-bank-sssp-20261012-v2.service
```

`manifest.json`, `environment.json`, `containment.json`, `preflight/`,
`execution.json`, and `supervisor.{stdout,stderr}.txt` describe the attempt.
The link adds `route.{stdout,stderr,progress,resources}.json/txt`, `summary.json`,
Vivado reports and, only on success, `candidate.hw.xclbin`.
If the hard cgroup limit kills the whole service, Python cannot write a final
JSON: a stale `ROUTING` file must **not** be treated as a live or successful
job. Check systemd `ActiveState` and `Result`, including `oom-kill`, and logs.

## Reproduction

Use a fresh attempt directory; do not rerun into a frozen or supervised one.
The pinned source files must remain unchanged while the service is queued
or running. Preparation checks the known production build and admitted
candidate rather than accepting arbitrary kernels.

```bash
BUILD=/data/tmp/chuxiao/grasu_regraph_sharded_k4_sssp_hw_b8d2ba3_20260806
ROOT=/data/chuxiao/experiments
BASIS=$ROOT/sharded_k4_cross_row_route_20261012/attempt-v1
STUDY=$ROOT/sharded_k4_directory_tile_20261012/hls-bank-wide-v1
HOST=$ROOT/sharded_k4_row_line_20261011/host-v2
INTEGRATION=/home/chuxiao/grasu-regraph-integration
ATTEMPT=$ROOT/sharded_k4_directory_bank_hw_20261012/attempt-fresh
MODULE=spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware

python3 -m "$MODULE" prepare --build "$BUILD" --basis "$BASIS" \
  --study "$STUDY" --host "$HOST" --integration "$INTEGRATION" --output "$ATTEMPT" \
  --allow-bounded-builds --background-memory-gib 6

systemd-run --user --unit=spine-sharded-k4-bank-sssp-fresh \
  --property=MemoryMax=40G --property=MemoryHigh=36G \
  --property=MemorySwapMax=0 --property=OOMPolicy=kill \
  --property=MemoryAccounting=yes --property=TasksMax=1024 \
  --property=CPUQuota=400% --property=Nice=10 \
  --property=RuntimeMaxSec=31h --property=TimeoutStopSec=15s \
  --property=KillMode=control-group \
  --property="StandardOutput=append:$ATTEMPT/supervisor.stdout.txt" \
  --property="StandardError=append:$ATTEMPT/supervisor.stderr.txt" \
  --working-directory="$PWD" \
  /usr/bin/python3 -m "$MODULE" supervise --build "$BUILD" --output "$ATTEMPT"
```

Do not run `supervise` directly in an unconstrained shell: it intentionally
refuses missing hard containment. A stopped or failed attempt needs a new
preparation and unit name, not an automatic restart with changed limits.

## Code And Checks

Owner: `spine_cycle_sim/experiments/sharded_k4_stages/row_line/directory_tile/hardware/`.
`preparation.py` owns evidence/ABI/input freezing; `containment.py` owns hard
limit verification; `admission.py` owns concurrent compiler reservations;
`supervisor.py` owns queue and execution.
Existing environment preflight, link watchdog and pidfd cleanup are reused.
No numerical C++/SST model or timing constants change.

```bash
python3 -m unittest discover -s tests -p 'test_sharded_k4_bank_hardware.py'
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware --help
```

The eight focused tests cover hard-limit refusal, unsafe admission,
other-build exclusion, stable admission, queue timeout, modified inputs,
clock/concurrency/ABI/selection rejection and fresh-attempt refusal. A real
small systemd probe verified 40/36-GiB limits, zero swap and group OOM policy
without large memory allocation. All 435 `test_sharded_k4*.py` tests passed;
six toolchain/environment preflight checks passed. Hardware speed remains
unmeasured.
