# SSSP Write-Issue Boundary Control

## Scope And Hypothesis

Simulator only; no FPGA build, routing, HLS edit or board measurement. This
control follows the [Apply interval audit](APPLY_SCHEDULE.md). It tests whether
counting the complete wrapper schedule before submitting explicit writes
explains the remaining complete-R prediction gap. It does not adjust memory
latency to make the candidate match A4.

An existing weighted-SSSP synthesis solution is read only:

`/data/tmp/chuxiao/grasu_regraph_weighted_sssp_normalized_v3_hw_20260726/build/kernelHBMWrapper/kernelHBMWrapper/kernelHBMWrapper/kernelHBMWrapper/solution`

Its `syn/report/write_out_csynth.xml` records tool 2024.1, part
`xcu55c-fsvh2892-2L-e`, target period 6.67 ns, II=1 and total depth 71.
Generated `syn/verilog/kernelHBMWrapper_write_out.v` enables both physical
ports' AWVALID in iteration 1, WVALID in iteration 2 and BREADY in iteration
70. All are guarded by the blocking pipeline condition. Therefore depth 71
includes the response wait; it is not evidence for 71 cycles of work before
issuing writes. The parser pins both artifacts and requires all six
handshakes, their stages and the report identity to agree.

The default-off `prefetch_sssp_write_issue` arm inherits
`prefetch_sssp_response`. Its only change is wrapper pre-request latency
71 -> 2, taking the later of the unstalled address/data stages. The model
still combines address and data in an AXI transaction: this is a conservative
source-backed boundary control, **not cycle-exact AXI or hardware calibration**.
Both physical replica writes, their explicit responses, finite pipeline
capacity 71, write credits 16 and the final acknowledgement barriers remain.
Production defaults and all preceding arms are unchanged.

## Fixed Comparison

Use the same Amazon real-ID slice: 258,046 vertices, 1,450,899 weighted edges
and four destination partitions. Every arm starts with the same old converged
source-0 state, resident post-update graph and prepared seed after three
weight decreases. All execute 46 synchronous rounds to final closure. Both
sides exclude G, host preparation, DMA and orchestration.

Predeclared matrix: A4-io16, unchanged response-timed candidate and write-issue
candidate; mock memory latencies 64/128; forward/reverse registration. All
twelve complete runs are required. Eight preceding rows must replay exactly;
state replicas, every active count and physical traffic must be conserved.
The candidate/A4 band is [0.9, 1.1] at **both** latencies. Candidate resources
remain sixteen physical masters/three state copies versus A4's thirteen/four.
This is not strict resource equivalence or reproduction of published ReGraph
FPGA numbers.

## Completed Result

| Mock latency | A4 cycles | Prior Apply-control cycles | Write-issue cycles | Candidate/A4 | Within 10% |
| --- | ---: | ---: | ---: | ---: | --- |
| 64 | 10,904,254 | 11,828,118 | 11,828,118 | 1.084725 | Yes |
| 128 | 15,840,606 | 19,699,546 | 19,699,546 | 1.243611 | No |

All twelve correctness runs pass. Eight old rows replay exactly, six
registration-order pairs agree, and full padded states/replicas, active
trajectories and bytes are conserved. The new control changes **zero complete
cycles** at either latency. Earlier request timing changes internal waits,
but is not a complete-path speedup here. Do not turn overlapping stall counts
into additive stage times or claim that the remaining gap is solved.

The candidate reads 2,021,232,640 bytes and writes 144,703,672 bytes; A4 reads
802,534,400 and writes 192,937,984. Complete performance retention still fails.
The numerical core is unchanged; its prior 37/37 tests are explicitly reused,
not rerun. Fresh experiment binaries pass nineteen configuration controls,
144 finite-input executions and four storage/backpressure probes.
Independent verification checks 2,595 pins, forty progress files, forty full
state files and every member of the run/pre-edit source archives
(2,395/2,394). See the [portable evidence index](wrapper_schedule.json).

## Safety And Reproduction

The service completes in 558.058 seconds, with a sampled cgroup peak of
1,207,939,072 bytes and zero swap. It has a 4-GiB hard/3-GiB high limit,
four workers pinned to CPUs 124--127, a live 24-GiB reserve and an 8-GiB
background budget. Atomic admission reserves competing finite budgets;
the watchdog may stop only owned work. The private small-memory profile
requires an unchanged, validated numerical core and cannot build a new core.
Fresh experiment harnesses are built against the pinned libraries.

The immutable pre-edit freeze is
`/data/chuxiao/experiments/r_sssp_wrapper_schedule_20261022/before/freeze.json`.
Choose a new service/output name:

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-sssp-wrapper-schedule-NEW \
  -p MemoryMax=4G -p MemoryHigh=3G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=40min -p 'CPUAffinity=124 125 126 127' \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.wrapper_schedule \
  --output /data/chuxiao/experiments/r_sssp_wrapper_schedule_20261022/convergence-NEW \
  --reference /data/chuxiao/experiments/r_sssp_apply_schedule_20261022/convergence-v1/results.json \
  --before /data/chuxiao/experiments/r_sssp_wrapper_schedule_20261022/before/freeze.json \
  --core-reference /data/chuxiao/experiments/r_prefetch_capacity_20261022/convergence-v2/results.json \
  --cpus 124 125 126 127

python3 -m unittest tests.test_regraph_wrapper_schedule \
  tests.test_regraph_compact_convergence -q
```

Source files in the completed campaign remain recoverable from its archive;
subsequent source edits cannot rewrite its report or its old-control replay.
The result does not admit the candidate as a production baseline, calibrate
hardware timing, close the G/host/integration gates or execute a new Spine
comparison. Further diagnostics must locate a remaining finite input/service
restriction rather than assume another interval adjustment will recover it.
