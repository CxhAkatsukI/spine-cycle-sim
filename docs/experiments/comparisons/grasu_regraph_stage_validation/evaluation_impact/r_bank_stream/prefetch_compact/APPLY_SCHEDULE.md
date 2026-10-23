# Response-Anchored SSSP Apply Control

## Question And Boundary

Simulator only. The [512-line candidate](PREFETCH_CAPACITY.md) reaches the
correct final state but takes 1.08514 / 1.24316 times A4 cycles at mock memory
latencies 64 / 128. The [passive diagnostic](WAIT_OVERLAP.md) identifies
overlapping backend waits; those counters cannot be summed into stage times.

There is a separate, auditable timing-boundary discrepancy. Integrated Apply
adds its configured 100 cycles **after** the old-state read response is
accepted (`grasu_regraph_apply.cpp::complete_read`). Original A4 already uses
an explicitly response-anchored, one-cycle SSSP interval. The integrated
100-cycle default is therefore not justified merely by citing an HLS pipeline
depth that includes its AXI read. This control tests that discrepancy rather
than choosing a latency to fit the desired total runtime.

## Source Evidence

An existing integrated weighted-SSSP synthesis solution is read only:

`/data/tmp/chuxiao/grasu_regraph_weighted_sssp_normalized_v3_hw_20260726/build/kernelApply/kernelApply/kernelApply/kernelApply/solution`

Its `Apply_Pipeline_Apply` report records II=1 and total depth 74. The detailed
schedule places old-state response consumption in state 73 and stream output
in state 74. Generated RTL enables `m_axi_gmem1_RREADY` in iteration 72 and
`prop_write_burst_stm_TVALID` in iteration 73. These independently support an
**unstalled response-to-output interval of one cycle**, not 74 or 100 cycles
after the response. Blocking AXI/stream interfaces can extend that interval.

The report, detailed schedule and RTL are pinned and checked together. This
is evidence for one component's timing boundary in an existing SSSP solution,
not new FPGA measurement, whole-path calibration or proof that the experimental
prefetch topology has been implemented in hardware. No synthesis, routing,
HLS edit or board test is launched for this study.

## Fixed Experiment

The explicit `prefetch_sssp_response` arm inherits the entire 512-line
candidate. Its only change is Apply post-response latency 100 -> 1, using
the existing named SSSP schedule constant. The production default and all
earlier arms remain unchanged. Memory latency/service, outstanding parents,
II, pipeline capacities, FIFOs, wrapper timing, state copies, physical masters,
PMA layout and complete convergence work do not change.

Use the same Amazon real-ID input: 258,046 vertices, 1,450,899 weighted edges,
old converged source-0 state and three weight decreases. Both sides receive
resident post-update input and execute all 46 synchronous rounds to final
closure. Exclude G, host preprocessing, DMA and orchestration on both sides.

Predeclared matrix: A4-io16, unchanged 512-line candidate, and the explicit
response-timed candidate; latencies 64 / 128; both component registration
orders. All twelve complete executions are required. Eight old-arm outputs,
cycles, counters and trajectories must replay exactly; new candidate state,
active trajectory and traffic must match the fixed references. Candidate/A4
cycles must lie in [0.9, 1.1] at both latencies for retention. No outcome is
presumed, and a passing row cannot cancel a failing row.

Resource accounting remains 16 physical masters/three state copies for the
candidate versus 13/four for A4. A numerical retention pass would not establish
strict resource equality, original-publication reproduction, hardware timing
calibration or production-baseline admission. It would also not complete the
G-stage, host-overhead or common warm-state Spine comparison gates.

## Validation And Reproduction

The pre-edit source archive, dirty diff, exact twelve-row reference and three
synthesis artifacts are indexed by
`/data/chuxiao/experiments/r_sssp_apply_schedule_20261022/before/freeze.json`.
The numerical C++ core is unchanged: reuse requires exact source coverage and
hashes, compiler/library/input pins and the prior complete 37/37 core regression.
The manifest explicitly labels those tests **reused, not rerun**. Fresh
experiment executables, eighteen resource controls and 144 finite-input cases
plus four storage/backpressure probes run before the complete matrix.

The owned CPU-only service has a 20-GiB hard/18-GiB high limit, zero swap,
four workers and a live 24-GiB reserve plus 8-GiB background admission budget.
An atomic lease reserves full competing finite budgets. Its watchdog stops
only owned work if the live reserve is breached. Choose a new output path:

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-sssp-apply-schedule-NEW \
  -p MemoryMax=20G -p MemoryHigh=18G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=40min -p 'CPUAffinity=124 125 126 127' \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.apply_schedule \
  --output /data/chuxiao/experiments/r_sssp_apply_schedule_20261022/convergence-NEW \
  --reference /data/chuxiao/experiments/r_prefetch_capacity_20261022/convergence-v2/results.json \
  --before /data/chuxiao/experiments/r_sssp_apply_schedule_20261022/before/freeze.json \
  --cpus 124 125 126 127
```

## Completed Result

All twelve `convergence-v1/` executions pass correctness and complete the same
46 rounds. Eight old configurations replay exactly. Full padded states,
replicas, active trajectories and physical bytes are conserved; both component
registration orders agree. Fresh configuration and finite-input checks pass.

| Mock memory latency | A4 cycles | Prior 512-line cycles | Response-timed cycles | Candidate/A4 | Reduction from prior | Within 10% |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 64 | 10,904,254 | 11,832,672 | 11,828,118 | 1.084725 | 0.03849% | Yes |
| 128 | 15,840,606 | 19,692,370 | 19,699,546 | 1.243611 | -0.03644% | No |

**Complete retention still fails.** The small latency-128 regression is
retained: changing queue arrival timing need not improve a contended finite
system monotonically. These totals do not attribute its cause to a particular
queue. The source-backed Apply boundary correction is valid to investigate,
but its net effect is below 0.04% here; it does not explain the remaining gap.
Do not select the latency-64 row alone or call the comparison calibrated.

The candidate still reads 2,021,232,640 bytes and writes 144,703,672 bytes,
versus A4's 802,534,400 and 192,937,984. Resource differences, excluded host/G
work and all non-admission boundaries above remain unchanged. The default
Apply interval remains 100; only the explicit experiment selects one cycle.

Independent verification rechecks 2,593 pins, 40 progress files, 40 complete
state files and all 2,393/2,392 members of the run/pre-edit source archives.
The [evidence index](apply_schedule.json) pins the raw report and archives.
The service finishes in 558.840 seconds, with a 1,207,980,032-byte peak and
zero swap. CPU simulator wall time is not a modeled accelerator latency.

## Remaining Timing Audit

Read-only inspection identifies a separate wrapper boundary to test, not a
measured optimization. `grasu_regraph_writeback.cpp` currently waits 71 cycles
after accepting an Apply burst **before** issuing the explicit AXI writes,
then waits for their responses. The existing integrated SSSP
`kernelHBMWrapper/.../solution/syn/report/write_out_csynth.xml` reports depth
71; its generated `kernelHBMWrapper_write_out.v` enables write address in
iteration 1, write data in iteration 2 and write-response acceptance in
iteration 70. Thus the total report depth is not evidence for 71 cycles of
pre-request work. Original A4's documented wrapper already separates explicit
write responses from report depth.

That observation needs its own source-pinned control: preserve both physical
replica writes, finite storage/credits and acknowledgement barriers, and replay
A4 plus the unchanged Apply experiment. It must not silently reinterpret the
combined AW/W transaction as a cycle-exact AXI implementation or assume that
an earlier write request will close the performance gap. No wrapper timing
change is executed or admitted in this record. No FPGA tool is needed for the
next simulator control.
