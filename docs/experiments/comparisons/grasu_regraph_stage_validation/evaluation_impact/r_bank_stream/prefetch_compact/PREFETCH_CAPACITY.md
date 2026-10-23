# Finite PMA Ring Capacity Control

## Preregistered Question

Simulator only; no HLS, routing, board run or paper edit. Can a larger, still
finite returned-data buffer improve overlap on the complete ready-burst R path?
The previous [whole-parent refill](READY_FULLBURST.md) candidate takes
1.08734 / 1.24729 times A4 cycles at mock memory latencies 64 / 128 and fails
the overall +/-10% retention gate. Full-burst refill alone did not explain it.
No improvement is presumed for this capacity experiment.

Each frontend's two reserved PMA rings grow from 256 to 512 64-byte lines.
Four frontends therefore add **128 KiB of data storage**, plus validity and
reservation flags. Pending and returned-but-unconsumed lines both reserve
capacity. Each physical master still has at most 16 parent requests and each
parent at most 16 beats. The increase permits more returned data to remain
buffered while subsequent parents are in flight; it grants no extra port,
instant response, lower latency, free read or relaxed output barrier.

The explicit `prefetch_ready_capacity512` arm inherits the existing ready-burst
schedule, triple input masters, split Apply and two finite directory tiles.
Default capacity remains 256. Invalid sizes and nondefault capacity on the
legacy physical-slot path are rejected before any memory request.
This is a new experimental architecture, not a production-profile replacement.

## Fixed Work And Gates

Use the same frozen Amazon real-ID graph (258,046 vertices, 1,450,899 edges),
old converged weighted SSSP state, three source-0 weight decreases, resident
post-update input and all 46 synchronous rounds to final closure. Exclude G,
host preprocessing, DMA and orchestration on both sides. The matrix has three
arms (`a4_io16`, `prefetch_ready_fullburst`, `prefetch_ready_capacity512`), two
mock memory latencies (64/128) and both component registration orders: twelve
complete executions. Clock, memory service and timing coefficients do not change.

Required gates, declared before execution:

- Eight old-arm observations replay exactly: cycles, all per-round active work,
  counters and output hashes. No tolerance is applied to old results.
- Candidate full state and active trajectory match A4; opposite registration
  orders agree exactly. Physical read/write bytes equal the previous candidate.
- All declared finite-storage and backpressure probes pass. The new sixteen
  executions have 1,306 physical segments, crossing the 512-line rings on
  both parities; the old 128 executions retain their old fixtures.
- Fresh core tests pass, including 72 complete compact-input correctness cases
  and invalid-capacity rejection; seventeen explicit resource controls pass.
- Candidate/A4 cycles must lie in [0.9, 1.1] at **both** latencies for performance
  retention. A faster lower-latency row cannot compensate for a failing row.
- Fresh default SST software compatibility must exactly replay five legacy
  cases. This does not calibrate the candidate's timing to hardware.

Resource comparison remains explicit: candidate 16 physical masters/three state
copies versus A4 13/four. Neither a performance pass nor this capacity change
establishes strict resource equivalence or reproduction of a published number.

## Complete-Matrix Result

**Correctness passes; overall performance retention fails.** All twelve
executions reach the same correct state after 46 rounds. Eight old-arm rows
replay exactly, including cycles, active trajectory, counters and output hashes.
Forward/reverse component registration agrees, and physical traffic is unchanged
from the 256-line candidate. The [evidence index](prefetch_capacity.json) records
the independent verification, software compatibility and delivery-check status.

| Complete R arm | Latency 64 cycles | Latency 128 cycles |
| --- | ---: | ---: |
| Original A4-io16 | 10,904,254 | 15,840,606 |
| Ready/full-burst, 256 lines | 11,856,592 | 19,757,874 |
| Ready/full-burst, 512 lines | 11,832,672 | 19,692,370 |
| 512-line candidate / A4 | 1.085143 | 1.243158 |
| Cycle reduction from 256 lines | 0.2017% | 0.3315% |

Only the latency-64 result meets the preregistered +/-10% band. The additional
128 KiB does not close the high-latency gap; it improves this complete workload
by less than 0.34%. This rejects this particular capacity increase as a useful
solution, not every possible buffer architecture or a general PMA limit.

Each candidate execution reads 2,021,232,640 bytes and writes 144,703,672 bytes;
A4 reads 802,534,400 and writes 192,937,984 bytes. Three rather than four state
copies reduce candidate writes, but do not erase its larger physical input.
These are conserved simulator ledgers, not FPGA measurements or energy values.

An additional blocked-consumer probe runs the unchanged Reader with both
capacities, latencies and registration orders (eight executions). It reaches
exactly 256 or 512 occupied lines as configured, verifies all 2,048 payloads,
and conserves 131,200 physical bytes, including both metadata reads. Thus the
extra capacity is exercised, not merely permitted by an upper-bound assertion.
All twenty shared full-burst progress CSVs also replay exactly, by both content
and hash. Five fresh default SST cases and independent artifact verification
pass; these are software compatibility checks, not hardware timing calibration.

No baseline promotion or new Spine comparison follows. The next useful
diagnostic is passive eligibility-to-issue observation in Apply and replica
publication: distinguish work not yet due from ready work blocked by credits,
request/output FIFOs, ordering or one replica port. Existing wait counters
overlap; their sums cannot assign exclusive portions of the remaining gap.
Changing a latency coefficient or granting free memory service is not a remedy.

## Reproduction

The pre-edit source archive, exact old twelve-row report and compiler/input/
binary pins are under `/data/chuxiao/experiments/r_prefetch_capacity_20261022/before/`.
Use a new output path and service name. The following is a CPU software build
and simulation only. The completed run uses a 6-GiB hard/5-GiB high owned
cgroup, no swap, one worker, a 24-GiB live reserve and 8-GiB background budget.
Unknown foreign
build budgets reject admission; live reserve violations stop only owned work.

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-prefetch-capacity-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=100min -p CPUAffinity=124 \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.prefetch_capacity \
  --output /data/chuxiao/experiments/r_prefetch_capacity_20261022/convergence-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --before /data/chuxiao/experiments/r_ready_fullburst_20261022/completion-v3/results.json \
  --freeze /data/chuxiao/experiments/r_prefetch_capacity_20261022/before/freeze.json \
  --cpus 124
```

The successful raw run is `convergence-v2/` under the same study root. It
completes fresh 37-target CTest, seventeen resource controls, 144 finite-input
executions, four backpressure probes and 72 complete compact-input correctness
executions, followed by the twelve-row real-input matrix. Core execution takes
approximately 36 minutes 49 seconds; simulator wall time is not device latency.
Its owned peak memory is approximately 1.03 GiB, with zero swap.

The supplemental capacity probe lives in
`cpp/tests/evaluation_impact/prefetch_compact/capacity_probe.cpp`; it compiles
against the same pinned core libraries and unchanged Reader. Its source,
binary, compiler command and eight outputs are indexed under
`capacity-checks-v2/`. The retained first attempt had a test-expectation error:
it counted the directory tile but omitted the separate 64-byte extent read.
Correcting that assertion changes neither the Reader nor the twelve-row
convergence results. `supplement_delivery.py` in the study directory records
the original bounded invocation and twenty-file counter replay; rerun its
recorded compiler command with a fresh binary/output path, preserving the
existing evidence directories.

`convergence-v1/` is a retained safety abort, not a numerical failure. Its
four-worker 20/18-GiB launch was admitted with sufficient available memory,
then stopped only its owned tree when the live reserve fell below 24 GiB.
No numerical gates had completed. The one-worker retry retains the same
workload and acceptance matrix; it changes host execution concurrency only.
Lifetime resource records and the original abort/watchdog files are indexed
without overwriting either attempt. SST compatibility uses a fresh software
plugin and five legacy cases; it does not establish candidate FPGA timing.
