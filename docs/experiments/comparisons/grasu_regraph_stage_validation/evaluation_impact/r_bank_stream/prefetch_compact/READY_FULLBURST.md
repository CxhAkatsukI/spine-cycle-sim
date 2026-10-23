# Whole-Parent Refill With Ready Output

## Declaration Before Execution

Simulator only. No HLS, FPGA build, routing, board run or paper edit.
Pre-edit source, compiler, input, binary, flags and complete ready-burst
reference are frozen under
`/data/chuxiao/experiments/r_ready_fullburst_20261022/before/` at commit
`ec27d0f`. Ready-burst R takes 1.0875 / 1.2474 times A4 at mock latencies
64 / 128; its overall retention gate fails.

Hypothesis: issuing a new small parent as soon as one ring slot is free can
consume the finite parent window without enough useful bytes in flight.
Test the existing full-parent reservation policy on the complete ready-burst,
triple-input, two-directory-tile path. A reader waits until the unchanged
256-line parity ring can reserve the next <=16-beat physical-bank-bounded
parent. It does not skip PMA slots or read future data without AXI responses.
This changes request grouping only: no new ports, capacity, state copies,
memory latency, issue interval, parent credits or timing coefficient.

The earlier isolated shared-master full-burst reader improved latency 64
slightly but regressed latency 128. That failure remains unchanged; it does
not predict success after the explicit complete-path topology changes.
This experiment can fail or regress. It is not permission to tune latencies.

## Matrix And Gates

Twelve complete warm-state weighted-SSSP executions: `a4_io16`,
`prefetch_ready_bursts`, `prefetch_ready_fullburst`; latencies 64/128 and
both component registration orders. Same Amazon real-ID slice, 258,046
vertices, 1,450,899 edges, four destination shards, three weight decreases,
old converged distances and final convergence. Resident post-update R only;
G, host preprocessing/orchestration, DMA and seed preparation are excluded.
Both R arms use the existing 150-MHz core clock and the same registered
Mock memory service (32 channels, latency 64/128, issue interval one,
32 backend credits). These are cycle-model assumptions, not FPGA timing.
Earlier isolated G studies use 200 MHz; their raw cycles must not be added
to these R cycles as a common-clock end-to-end result.

Require exact replay of eight old controls, full padded state and active
trajectory equality with A4, registration-order equality, physical byte
conservation, bounded buffering, complete request/beat closure and no lost
terminal markers. Existing 32 full-burst synthetic cases exercise bank tails,
ring wrap and throttling. Add the explicit integrated arm to all four compact
correctness cases in both registration orders, plus rejection on a legacy
physical-slot input. Fresh complete core and default SST checks are required;
SST compatibility is not timing calibration of this default-off experiment.

Expected direction: fewer fragmented parents may reduce high-latency waits.
Retention remains candidate/A4 in [0.9,1.1] at **both** latencies. Preserve a
failed or regressing arm. Candidate physical masters remain 16 versus A4's
13, state copies three versus four; no strict resource-equivalence or
original-paper hardware reproduction claim. No new Spine claim follows.

The first attempt used one worker, 6/5-GiB max/high and zero swap. Its live
24-GiB reserve was breached by machine-wide memory pressure during core
regression, before the performance matrix. The watchdog killed the owned
cgroup at a peak of 850,935,808 bytes. Preserve the incomplete attempt under
`/data/chuxiao/experiments/r_ready_fullburst_20261022/convergence-v1/`, including
`reserve_failure.json`; it provides no new performance result.

Before the second attempt, available memory recovered to about 74 GiB.
Use the existing four-worker profile, CPUs 124--127, 20/18-GiB max/high,
zero swap, atomic admission and the unchanged live 24-GiB reserve plus
8-GiB background allowance. No numerical configuration changes between
attempts. Keep source-pinned owners unchanged while execution is live.
The thin `ready_fullburst.py` entry point reuses the complete convergence
runner and analysis, not a duplicate simulation engine.

The second service also encountered a transient live-reserve breach. It
completed all 37 core tests, finite-input probes and nine complete matrix
rows before the watchdog killed its owned group. Machine available memory
was 24,313,114,624 bytes at the last sample; the service itself peaked at
1,457,446,912 bytes with zero swap. Preserve its report and failure under
`convergence-v2/`; its last saved running status is not a completed campaign.

Completion uses a fresh `completion-v3/` folder and a bounded recovery helper
retained with the raw evidence. Before reuse, it verifies every source,
compiler, input and binary pin, every successful step, all nine saved stdout
observations and complete output hashes. It copies only completed states and
progress, then executes the remaining three declared cases with the exact
same binary and memory-model settings. It does not rebuild numerical code,
lower the 24-GiB reserve, overwrite either failed attempt, or treat incomplete
outputs as observations. The completion service retains 20/18-GiB max/high,
zero swap and three workers. All twelve rows must pass the original analysis
before a combined conclusion is permitted.

## Execution Status

All twelve declared complete-convergence executions now pass state, active
trajectory, physical-traffic, request closure and registration-order checks.
The eight shared controls replay the preceding ready-burst campaign exactly.
The second attempt's nine completed rows were verified and reused; three
remaining rows completed in the separate recovery service, without rebuilding
the binary or changing numerical inputs. Neither interrupted attempt is
relabeled as complete.

| Complete 46-round R computation | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| Original A4-io16 | 10,904,254 | 15,840,606 |
| Previous ready-burst input | 11,858,340 | 19,758,840 |
| Whole-parent refill on ready input | 11,856,592 | 19,757,874 |
| New candidate / A4 | 1.08734 | 1.24729 |
| Cycle reduction from previous input | 0.01474% | 0.004889% |
| Within the declared +/-10% band | Yes | **No** |

**The complete performance-retention gate fails.** Whole-parent refill has
negligible effect on this topology. It does not explain or close the remaining
high-latency gap. Preserve the older isolated refill regression as well;
neither result permits declaring a general improvement or selecting only the
passing latency. The flag remains default-off, not a production replacement.

Each new execution reads 2,021,232,640 physical bytes and writes 144,703,672,
exactly matching the previous ready-burst arm. A4 reads 802,534,400 bytes and
writes 192,937,984. The candidate still pays for PMA, directory and source
traffic; fewer packets or different parent grouping do not remove those
physical reads. Candidate read volume is about 2.519 times A4, but that ratio
alone does not determine runtime because concurrent requests and downstream
backpressure overlap. Passive frontend/Apply waits are not additive stage
costs or proof of a unique bottleneck.

The next diagnosis should distinguish finite lookahead/storage limits from
downstream waiting on this exact complete path. Any larger buffer must be a
separate declared capacity control with explicit added bytes, unchanged old
arms and unchanged physical memory service. No timing-factor adjustment,
extra free port or hidden state copy is justified by this failed test.

Fresh validation passes: 37 core CTest targets, 16 explicit resource
controls, 128 finite-input executions, four publisher storage/backpressure
probes and 64 compact complete-correctness executions. A separately rebuilt
SST CPU plugin exactly replays all five default cases: 99,885 / 5,997,674
cycles for mixed/multipart SSSP, 133,841 for CC, 1,487,890 for warm residual
PR and 200 for update-only. Compatibility does not establish candidate
hardware timing or original-paper reproduction.

Independent verification checks 2,405 core pins, 2,766 SST pins, all 40 full
state files and 40 progress files, both source archives and the pre-edit
artifacts/inputs: zero mismatches. The portable
[evidence index](ready_fullburst.json) links the complete matrix, validation,
recovery and memory-safety reports, including all interrupted attempts.
Delivery checks also pass: 131 ReGraph Python tests, 15 organization tests,
document layout, generated catalogs and staged/unstaged whitespace checks.

The first fresh SST software attempt also hit the unchanged 24-GiB live
reserve while compiling. Its last available-memory sample was 23,827,238,912
bytes; its own sampled peak was 1,076,408,320 bytes with zero swap. Preserve
`sst-v1/` as interrupted, not as a failed numerical comparison. Retry in
`sst-v2/` with the same 6/5-GiB hard/high budget, zero swap, admission and
live-reserve protection. The completed twelve-case core matrix is unaffected.
The retry completed in 507.067 seconds, with a lifetime cgroup peak of
1,130,659,840 bytes and zero swap. Independent verification then completed
in 2.392 seconds, peaking at 44,687,360 bytes. These are CPU software-run
resources and wall times, not modeled accelerator cycles.

Raw complete evidence is under
`/data/chuxiao/experiments/r_ready_fullburst_20261022/completion-v3/`.
The pre-edit freeze, both safe-abort folders and recovery helper remain in
the same campaign root. The entire baseline objective remains open: this
is R-only evidence, not completion of the separate G, host or Spine demo work.

## Ownership And Reproduction

The existing finite reader owns request grouping in
`cpp/src/detail/prefetch_compact/requests.hpp`. The explicit configuration flag
and private routed-input owner select that policy without duplicating a
reader or changing a default. The thin Python entry point
`spine_cycle_sim/experiments/evaluation_impact/r_bank_stream/ready_fullburst.py`
reuses the complete convergence runner and state/traffic analysis. See the
[C++ ownership guide](../../../../../../../cpp/tests/evaluation_impact/prefetch_compact/README.md).

From the simulator worktree root, use fresh unit and output names:

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-ready-fullburst-NEW \
  -p MemoryMax=20G -p MemoryHigh=18G -p MemorySwapMax=0 \
  -p OOMPolicy=kill -p RuntimeMaxSec=100min \
  -p 'CPUAffinity=124 125 126 127' -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.ready_fullburst \
  --output /data/chuxiao/experiments/r_ready_fullburst_20261022/convergence-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --before /data/chuxiao/experiments/r_ready_bursts_20261022/convergence-v1/results.json \
  --freeze /data/chuxiao/experiments/r_ready_fullburst_20261022/before/freeze.json \
  --cpus 124 125 126 127

python3 -m unittest tests.test_regraph_ready_fullburst \
  tests.test_regraph_ready_bursts -v
```

The runner admits the complete finite budget atomically and monitors the live
reserve. Keep pinned numerical owners unchanged until the core campaign and
its fresh default SST software replay finish. The latter builds a CPU plugin;
it does not compile FPGA hardware or establish candidate timing calibration.
