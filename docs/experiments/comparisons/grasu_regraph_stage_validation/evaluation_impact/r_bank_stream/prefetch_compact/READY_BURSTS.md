# Finite Ready-Burst Output

## Declaration Before Implementation

Simulator-only follow-up to [directory lookahead](DIRECTORY_OVERLAP.md).
No FPGA build, HLS change, board run or paper edit is part of this study.
Pre-edit sources, compiler, inputs, binary and complete reference are frozen
under `/data/chuxiao/experiments/r_ready_bursts_20261022/before/` at commit
`219c9d5`. The preceding candidate takes 1.479 / 1.552 times A4 at mock
latencies 64 / 128; neither retention gate passes.

Hypothesis: fixed whole-partition draining blocks ready workers behind a busy
worker. Test a default-off four-way round-robin arbiter that locks one worker
for eight consecutive rows (16 vertices), then chooses a ready worker again.
Each row still pays its registered mux cycle. The merger keeps its existing
eight-row packer and pending burst; addressed bursts carry their actual global
offset through Apply and publication. No complete output partition is copied
into a new reorder buffer. Per-worker partition order remains unchanged.

Apply preserves arrival order with a finite offset queue bounded by its
existing pipeline capacity (100 offsets in this experiment), in addition to
four coverage counters. Merger
and writeback check complete unique coverage with four counters each, not an
unbounded bitmap. All requests, state replicas, clock, memory latency, bank
service, source caches and input masters remain as in directory lookahead.
This is an experimental output protocol, not a hardware timing claim.

## Predeclared Matrix And Gates

Twelve complete weighted-SSSP executions: `a4_io16`,
`prefetch_directory_lookahead`, and `prefetch_ready_bursts`; latencies 64/128;
both component registration orders. Same resident post-update PMA, Amazon
real-ID slice (258,046 vertices, 1,450,899 edges), four destination shards,
old converged distances, three weight decreases and final convergence.
No G, preparation, host orchestration or DMA is included in this boundary.

Require eight old controls to preserve cycles, counters, trajectory and state
exactly; candidate full padded state and 46-round active trajectory equal A4;
registration-order equality; finite-buffer bounds; no duplicate/missing row;
request/beat/byte conservation and unchanged physical traffic from directory
lookahead. Test delayed workers, stalls within a burst, more than four
partitions, restart and malformed addresses. Fresh complete CTest and default
SST compatibility must pass; the latter is software regression, not timing
calibration of this candidate.

Expected direction: less output head-of-line blocking, with no guarantee of
meeting the target. The unchanged retention gate is candidate/A4 in [0.9,1.1]
at both latencies; A4 is an independent same-input model, not the original
paper's measured hardware performance. Candidate masters remain 16 versus
A4's 13, and state copies three versus four: no strict resource-match claim.
Use one worker under 6/5-GiB max/high, zero swap, a live 24-GiB reserve and
8-GiB background allowance. Preserve a failure rather than tune coefficients.

## Complete-Convergence Result

All twelve declared executions finish correctly, each with 46 complete rounds.
The eight pre-edit controls replay exactly, and all six forward/reverse
registration pairs agree. Candidate padded state replicas and active-count
trajectories equal A4. No physical traffic is removed by this change.

| Memory latency | A4 cycles | Directory lookahead cycles | Ready-burst cycles | Ready/A4 | Reduction from directory | Within 10% |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 64 | 10,904,254 | 16,128,290 | 11,858,340 | 1.08750 | 26.47% | Yes |
| 128 | 15,840,606 | 24,591,738 | 19,758,840 | 1.24735 | 19.65% | No |

**Overall retention fails.** Passing latency 64 alone is not the declared
two-latency acceptance gate. The experimental path remains default-off;
G, host timing, complete baseline admission and a new Spine comparison are
unfinished. A4 here is the independent source-derived four-Little simulator,
not a measurement from the original ReGraph paper.

The candidate reads 2,021,232,640 bytes and writes 144,703,672 bytes over the
complete computation, exactly matching directory lookahead. A4 reads
802,534,400 bytes and writes 192,937,984 bytes. The PMA scan and physical
padding still cost traffic; output scheduling does not eliminate them.
The candidate has 16 physical masters and three state copies, versus A4's
13 masters and four copies. This is not strict resource equivalence.

The cycle reduction, with unchanged input work and memory service, supports
output head-of-line blocking as one important restriction of the preceding
path. It does not assign every remaining cycle to the adapter. Input/source,
Apply and writeback waits overlap; their counters are not additive stage
times. Input completion endpoints also include downstream backpressure.

## Validation And Evidence

Fresh Release CTest passes all 37 targets, including finite addressed-burst
coverage, delayed workers, stalls within a burst, restart and malformed
offsets. The harness passes fifteen explicit configurations, 128 finite-input
executions, four publisher probes and 56 complete compact-input executions.
All five source-pinned default SST regressions reproduce their preceding
cycles and request/state ledgers exactly. ReGraph Python checks pass 128
tests, and repository organization checks pass 15. Document layout, generated
catalogs and staged/unstaged whitespace checks pass. These results are recorded
in the [compact evidence index](ready_bursts.json); default SST compatibility
is not candidate timing calibration or a new hardware result.

Raw evidence is under
`/data/chuxiao/experiments/r_ready_bursts_20261022/`: `before/` is the
pre-edit freeze, `convergence-v1/` contains all matrix rows, full states,
progress, compilation and core checks, `sst-v1/` owns the fresh default
compatibility check, and `quality-v1/` owns Python and organization checks.
Independent `verification.json` confirms all 2,400 core pins, 2,761 SST pins,
40 progress files and 40 full-state files; it also verifies all members of
both source archives and the external pre-edit dependencies. No mismatch is
accepted by the verifier.
The compact index preserves hashes without duplicating machine-local logs
or thousands of source pins in Git.

The complete core campaign used one worker, 6/5-GiB max/high, zero swap,
a 24-GiB live reserve, atomic admission and a live memory watchdog. Its
service took 2,318.450 seconds and peaked at 847,036,416 bytes. CPU simulator
wall time is not device-cycle latency.

## Ownership And Reproduction

The [C++ ownership guide](../../../../../../../cpp/tests/evaluation_impact/prefetch_compact/README.md)
describes the finite resources. `regraph_burst_order.hpp` owns coverage;
`routed_regraph/transport.cpp` owns arbitration. Merger, Apply and writeback
retain their numerical and memory-service owners. The thin Python study
`ready_bursts.py` reuses the common complete-convergence runner and exact
state/traffic analysis instead of creating another execution engine.

From the simulator root, choose a **fresh** unit and output directory:

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-ready-convergence-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 \
  -p OOMPolicy=kill -p RuntimeMaxSec=100min -p CPUAffinity=124 \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.ready_bursts \
  --output /data/chuxiao/experiments/r_ready_bursts_20261022/convergence-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --before /data/chuxiao/experiments/r_directory_overlap_20261022/convergence-v1/results.json \
  --freeze /data/chuxiao/experiments/r_ready_bursts_20261022/before/freeze.json \
  --cpus 124

python3 -m unittest tests.test_regraph_ready_bursts \
  tests.test_regraph_directory_overlap tests.test_regraph_apply_ports -v
```

Keep source owners unchanged while the source-pinned campaign runs. The
live memory watchdog and atomic admission are enforced inside the runner;
an outer cgroup alone does not replace those checks. This is CPU simulator
execution, including an SST software plugin regression, not FPGA compilation.
