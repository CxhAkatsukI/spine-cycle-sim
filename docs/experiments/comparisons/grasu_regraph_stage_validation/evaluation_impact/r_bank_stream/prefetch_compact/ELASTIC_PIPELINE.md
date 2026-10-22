# Explicit Dual-Reader And Elastic-Pipeline Experiment

## Scope And Current Decision

Simulator only. All twelve fresh complete-convergence executions pass
correctness, but the performance-retention gate fails at both memory
latencies. The candidate takes 1.787 / 2.209 times strong A4 cycles; it is
29.05% faster than the preceding source-loading path at latency 64 and
2.73% slower at latency 128. It remains default-off. This study changes
neither the original A4 control nor a production default. It does not
rebuild FPGA logic, edit the paper, replace Figures 7--11, or admit a new
G+R/Spine comparison. See [source loading](SOURCE_LOADING.md) for the
preceding integrated result and [evidence index](elastic_pipeline.json)
for this campaign's pinned reports and explicit non-admission flags.

The hypothesis follows the negative [full-burst result](BURST_REFILL.md).
A depth-two, latency-two pipeline checks admission before the clock edge;
an entry retiring at that edge cannot provide a new admission slot. A third
finite slot can remove that storage bubble without shortening the modeled
latency or changing same-edge FIFO semantics for other components.

## Frozen Before State

The authoritative pre-edit checkpoint is `cf9d368`. Its freeze lives at
`/data/chuxiao/experiments/r_elastic_pipeline_20261022/before/freeze.json`.
It records source identities, a source archive, and the old reader and
complete-convergence reports. It does not contain a separate dirty diff or
compiler executable pin. Compiler/build identities remain in the referenced
completed campaigns; the fresh campaign archives and pins the actual edited
source, compiler, inputs and references before building it, then pins the
new build configuration and binaries before executing the matrix.

`integration-before/` is an additional working snapshot, not the authority
for the original checkpoint. Its archive command was asynchronous relative
to the integration edit, so it must not be used to prove a pre-edit identity.
Failed `smoke-v1/` and `smoke-v2/` attempts are retained: a probe incorrectly
expected post-commit peak occupancy three at an unthrottled sink. The third
slot is needed at admission, but simultaneous retirement leaves occupancy
two after commit. The corrected `smoke-v3/` probe checks both observations.

## Explicit Architecture

The default reader and publisher still use capacity two. The new default-off
`RoutedInputPath::kDualPrefetchElasticExperimental` selection combines:

- Two physical input AXI masters per frontend. Metadata and even PMA lines
  use the first; odd PMA lines use the second. This is not a free virtual
  channel or an increased return rate on one master.
- Capacity three for both the segment pipeline and packet publisher, with
  latency two unchanged. All reservations and returned data remain bounded.
- The preceding independent source-cache loading schedule. Cache capacity,
  one-window lookahead, data-return requirements and round barriers remain.
- The same two 256-line PMA rings per reader, 1024-row directory tile,
  sixteen parents per master, sixteen-beat parent limit, registered memory
  arbitration and 71-cycle minimum modeled issue-to-use delay.

Gather, merger, Apply, state publication, memory latency and backend credits
are unchanged. The complete candidate has eleven physical masters and three
state copies; the prior source-loading candidate has seven masters. Strong
A4 still has thirteen masters on nine banks and four state copies. Neither
the master count alone nor the number of frontends proves resource equality.

## Isolated Probe Results

The corrected saturated same-source-window publisher probe emits 2,048
packets with exactly the same payload and terminal marker:

| Capacity | Pipeline latency | Sink period | Cycles | One-cycle output gaps | Two-cycle output gaps | Post-commit peak |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 2 | 2 | 1 | 3,076 | 1,024 | 1,023 | 2 |
| 3 | 2 | 1 | 2,053 | 2,047 | 0 | 2 |
| 2 | 2 | 5 | 10,241 | 0 | 0 | 2 |
| 3 | 2 | 5 | 10,241 | 0 | 0 | 3 |

Both registration orders agree, and the throttled sink exercises bounded
backpressure. All 96 finite-input synthetic executions and four publisher
configurations also pass against the freshly built Release libraries. All
36 CTest targets pass. These are component correctness/compatibility checks,
not complete-R speedups or FPGA timing.

The preliminary dual-reader/elastic stall-free real-input scan takes 247,618
cycles at latency 64 and 453,372 at latency 128. Both read the same 38,696,960
physical bytes and emit 1,450,899 edges in 181,464 packets. Compared with the
depth-two dual-reader diagnostic, this improves latency 64 by 15.21% but
slightly regresses latency 128 by 0.106%. The conditional 46-scan floors are
1.045 / 1.317 times complete A4; they are not complete convergence results.
The latency-128 floor still exceeds the 1.10 target before computation.

## Complete-R Results

| Arm | Latency 64 cycles | Latency 128 cycles |
| --- | ---: | ---: |
| Strong original A4 (`a4_io16`) | 10,904,254 | 15,840,606 |
| Previous source-loading path | 27,465,634 | 34,058,814 |
| Dual-reader/elastic candidate | 19,487,578 | 34,988,382 |
| Candidate / A4 | 1.7872 | 2.2088 |
| Cycle reduction from source-loading | 29.05% | -2.73% |

Both registration orders agree. All eight old A4/source rows replay exactly;
all twelve executions match final padded state and active-count trajectories.
Every arm completes 46 rounds. The candidate combines additional physical
reader ports and pipeline storage, so the latency-64 improvement cannot be
attributed to the third slot alone. The latency-128 regression is retained,
not averaged away or dropped from the decision.

Physical traffic is unchanged from the source-loading path: 2,021,232,640
read bytes and 144,703,672 write bytes. A4 reads 802,534,400 and writes
192,937,984 bytes, with four rather than three state replicas. Candidate
read traffic is still 2.519 times A4; empty PMA lanes and directory access
have not been removed for free.

### What The Passive Counters Say

The four fixed destination-shard workers emit 58.44%, 25.56%, 11.79% and
4.21% of the packets, unchanged from the preceding path. Original A4 uses
four subtasks within a destination partition instead; these are different
task layouts, not a strict resource-matched experiment.

At latency 64 the sum of per-round last-adapter completion offsets falls
from 20,951,942 to 12,973,886 cycles. Complete cycles fall by the same
7,978,056; the tail after all frontends stays 26,818 cycles. At latency 128
the adapter offsets increase from 21,515,672 to 22,445,240, while complete
cycles increase by the same 929,568. Its tail stays 47,656 cycles. Backend
wait counters are identical between old and new paths at each latency.

These are overlapping completion offsets, not additive stage times or proof
of a unique bottleneck. They support further investigation of input issue
and wait behavior, fixed-shard imbalance and ordered partition draining.
The local publisher bubble is real, but eliminating it does not recover
complete-R retention. No memory latency or timing coefficient was changed
to hide the remaining gap.

## Complete-Convergence Gates

Use the same frozen Amazon real-ID slice: 258,046 vertices, 1,450,899 weighted
edges, four destination shards and three source-0 weight decreases from old
converged SSSP state. Complete all 46 synchronous rounds at 150 MHz. Both
inputs and seed are resident; G, host work and DMA are excluded equally.

The matrix has twelve executions: `a4_io16`, `prefetch_source`, and
`prefetch_dual_elastic`, each at latency 64/128 and both registration orders.

1. Build a fresh Release core; pass all 36 CTest targets and explicit control
   admission checks. The integrated compact-input test covers 24 cases,
   including the new path, empty/throttled input, source-window crossings,
   more than four partitions and terminal-marker/restart rules.
2. Freshly compile the finite-input harness against those new libraries;
   pass all 96 synthetic executions and four publisher probe configurations.
3. Reproduce all eight old A4/source-loading rows exactly, including cycles,
   counters, active-count trajectories and every final-state output hash.
4. Require final padded state in all three candidate replicas and every
   round's active count to match the independent oracle/A4. This is not a
   complete intermediate-state capture. Both registration orders must agree.
5. Close every request, beat, physical input lane and publication write.
   Read/write bytes must equal the preceding complete source-loading path.
6. Candidate/A4 must remain within 0.9--1.1 at both memory latencies for the
   declared retention gate. Correct execution alone does not pass this gate.
7. Build the SST software plugin freshly and exactly replay all five default
   cases. This is software compatibility, not hardware or stage calibration.
8. Verify source, compiler, frozen input, reference, binary and progress pins
   at completion. Do not edit numerical owners while either campaign runs.

Gates 1--5, 7 and 8 pass. Gate 6 fails at both latencies. The freshly built
SST plugin exactly replays all five default cases, including result hashes,
cycles and counters, with zero rejected cases. All 2,748 SST source/input/
reference pins remain unchanged. This is default-path software compatibility;
it cannot change this retention decision or establish candidate timing.

## Owners And Reproduction

The finite reader/publisher remain in `cpp/src/detail/prefetch_compact/`.
The named integrated input owner is `cpp/src/routed_regraph/input.cpp`;
composition and admission explicitly wire/check the extra masters. The thin
Python CLI and matrix analysis are `elastic_pipeline.py` and
`elastic_analysis.py` in the existing R-study package. Tests live beside
the prior input/control and Python study checks, not in a new top-level runner.

The raw root is `/data/chuxiao/experiments/r_elastic_pipeline_20261022/`.
Use unused unit/output names from the repository root:

```sh
systemd-run --user --wait --pipe --collect --unit=spine-r-elastic-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=100min -p CPUAffinity=124 -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.elastic_pipeline \
  --output /data/chuxiao/experiments/r_elastic_pipeline_20261022/convergence-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --before /data/chuxiao/experiments/r_source_overlap_20261022/convergence-v1/results.json \
  --cpus 124
```

The separate fresh SST software check is:

```sh
systemd-run --user --wait --pipe --collect --unit=spine-r-elastic-sst-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=45min -p CPUAffinity=124 -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.software_compatibility \
  --output /data/chuxiao/experiments/r_elastic_pipeline_20261022/sst-NEW \
  --core-result /data/chuxiao/experiments/r_elastic_pipeline_20261022/convergence-NEW/results.json \
  --baseline /data/chuxiao/experiments/sharded_k4_bank_stream_profile_20261019/gates-v1/legacy_final
```

The service is single-worker, zero-swap, with a live 24-GiB reserve and
8-GiB background allowance; per-case timeouts and cycle limits remain finite.
Admission requires own hard limit plus reserve and peer/background budgets,
not merely the current process RSS. At launch about 41 GiB was available,
so the 20-GiB parallel profile was not used. No foreign process is stopped.
The complete core campaign finished in 34 minutes 42 seconds with a
867,360,768-byte cgroup lifetime memory peak (about 827.1 MiB).
The fresh SST build and five-case replay take another 8 minutes 30 seconds,
with a 1,043,161,088-byte peak (about 994.8 MiB). Neither invokes FPGA tools.
