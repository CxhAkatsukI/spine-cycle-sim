# Separate Apply-Master Experiment

## Scope And Decision

Simulator only. The preceding [metadata-port candidate](METADATA_PORTS.md)
takes 1.598 / 1.937 times strong original A4 cycles. The next controlled
question is whether its combined Apply read/write parent pool limits
concurrency. This is an explicit default-off architecture experiment, not
a correction to measured hardware or a timing-coefficient fit.

`RoutedApplyTopology::kSplitMastersExperimental` gives Apply reads their own
physical AXI master. Apply writes and final status share the other master.
Both use the same HBM channel 30, unchanged memory latency, bank service,
sixteen parent slots per master and registered routing. The singleton read
mux retains the original routing hop. Apply's sixteen-entry request window,
pipeline capacity, memory contents and arithmetic are unchanged. Source
writeback remains on channels 23/24. No HBM bank or bandwidth is added.

The complete candidate has **16 physical masters**, versus 15 for the
preceding candidate and 13 for A4. It adds physical parent/response storage
and issue capability; it is not strict resource equivalence. The candidate
has three state copies versus A4's four. Physical PMA, metadata and state
traffic must remain identical to the preceding candidate.

All profiles and old controls retain combined Apply by default. The new
arm is `prefetch_triple_split_apply`; its input remains the triple-master,
finite elastic-prefetch candidate. No HLS, FPGA tool, board, paper or figure
is changed. Production promotion and a new Spine comparison remain separate.

## Frozen Reference And Gates

The pre-edit source is commit `20a263abbfc6441258ac54a8b3fcaf04d4eec2dd`.
`/data/chuxiao/experiments/r_apply_ports_20261022/before/freeze.json` pins
its committed-source archive, empty dirty diff, compiler and completed
metadata-port reference. Fresh source, compiler, input, build and output
identities are additionally pinned by the shared convergence runner.

The declared matrix has twelve executions: strong original A4, unchanged
triple input/shared Apply and triple input/split Apply; mock latency 64/128
and forward/reverse registration. The unchanged Amazon real-ID slice has
258,046 vertices, 1,450,899 weighted edges and four destination shards.
Both sides start with resident post-update PMA, old converged SSSP state
and three source-0 weight decreases, and run all 46 synchronous rounds to
convergence/publication at 150 MHz. G, preparation, host, DMA and orchestration
are excluded on both sides. This is not full Amazon or paper reproduction.

1. Fresh Release core: all 36 CTest targets, forty integrated compact-input
   executions, default-preservation checks and explicit topology controls.
   Invalid Apply topology and initiator overflow must fail before traffic.
2. Preserve all 112 finite-input executions and four publisher-storage probes.
3. Exactly replay eight preceding A4/triple controls: cycles, physical traffic,
   round active counts and final padded state. Registration order must agree.
4. Match the independent oracle, every round's active count and final state
   replicas. Keep request, beat, byte and packet conservation intact.
5. Preserve preceding candidate read/write byte totals. Do not omit metadata,
   padding, source writeback or final publication to improve the ratio.
6. Require candidate/A4 in **0.9--1.1 at both latencies**; retain failed rows.
7. Fresh SST software build and exact five-case default replay. This is
   compatibility, not candidate timing calibration or hardware admission.
8. Reverify all source, compiler, input, binary, reference and progress pins.

No numerical owner may change while a pinned campaign is executing.
Passive completion offsets and wait observations overlap; they must not
be added as exclusive stage costs.

## Result

The fresh `convergence-v2` campaign completes all twelve executions. Every
arm reaches the independent oracle in 46 rounds with identical active counts
and final padded state. All eight preceding controls replay exactly; all six
forward/reverse numerical pairs agree. **Both retention gates still fail.**
The [evidence index](apply_ports.json) pins the raw reports, checks, selected
source/build identities and passive observations.

| Complete-convergence cycles | Latency 64 | Latency 128 |
| --- | ---: | ---: |
| Strong original A4, unchanged | 10,904,254 | 15,840,606 |
| Triple input, shared Apply, unchanged | 17,419,740 | 30,685,450 |
| Triple input, separate Apply masters | 16,950,908 | 24,619,522 |
| Candidate / A4 | 1.554522 | 1.554203 |
| Reduction from preceding candidate | 2.6914% | 19.7681% |

These are simulator cycles, not simulator wall time or hardware measurements.
Each candidate execution reads 2,021,232,640 physical bytes and writes
144,703,672 bytes, exactly matching the preceding candidate. A4 reads
802,534,400 bytes and writes 192,937,984 bytes; its four state replicas differ
from the candidate's three. The candidate neither removes physical PMA reads
nor receives a new HBM bank. Extra physical-master storage is paid explicitly.

The fresh Release core passes all 36 CTest targets, including forty integrated
compact-input executions. The thirteen-arm control, all 112 finite-input
executions and four publisher-storage probes pass. All 2,392 source, compiler,
input, binary and reference pins plus forty progress pins were reverified.
The fresh SST software build and all five default cases replay exactly,
including correctness, cycles, counters and result identities. Its 2,753
source, compiler, input, binary and reference pins were reverified. This is
default-path compatibility, not candidate timing calibration; it does not
turn either failed performance gate into a pass.
All 121 focused ReGraph Python tests and fifteen repository-organization
tests pass, along with document-layout, catalog and diff checks. Their
commands, resource records and log identities are in the evidence index.

Both campaigns use one CPU and a 6-GiB cgroup limit, 5-GiB high threshold
and zero swap. Complete core testing takes 38 minutes 37 seconds with an
847,249,408-byte service peak; fresh SST build/replay takes 8 minutes
36 seconds with a 1,044,602,880-byte peak. These are host execution costs,
not predicted accelerator latency.

## Remaining Gap

At latency 64, recorded Apply read/write waits and merger output stalls fall
to zero, but complete cycles improve only 2.69%. At latency 128, Apply write
waits fall from 11,758,658 to zero, read waits fall from 11,753,644 to 5,693,696,
and merger output stalls fall from 6,471,326 to 417,312. The 19.77% improvement
supports shared Apply concurrency as one high-latency restriction, not the
complete explanation for the remaining gap. These counters overlap and are
not additive stage times.

The adapter completion offsets are unchanged: 10,906,048 / 18,142,308 cycles
summed over the 46 rounds. Candidate final frontend completion is
16,934,762 / 24,586,954; the final tail is only 16,146 / 32,568 cycles.
Waiting until after the final frontend is therefore not most of the remaining
window. This is an overlapping-endpoint observation, not exclusive attribution.

The four workers carry 58.44%, 25.56%, 11.79% and 4.21% of compacted packets.
Source inspection also confirms fixed partition-order Gather draining.
An already-ready later partition can wait behind an earlier partition; a
zero merger-stall counter does not exclude this head-of-line wait. A4 instead
uses its four Little pipelines within each destination task. These different
task schedules and remaining PMA/metadata reads need separate investigation.

At latency 128, the unchanged adapter completion is 1.145304 times A4's
complete window, above the 1.1 retention ceiling under this output schedule.
Interpretation correction in the [directory-lookahead follow-up](DIRECTORY_OVERLAP.md):
this endpoint includes downstream backpressure. It is not an intrinsic input
floor, so it does not prove that output reordering alone must fail. Round
publication cannot precede input completion, but a changed output schedule
can also change when that input completes. The recorded measurements and
failed retention decision are unchanged.

Next isolate a finite ready-partition drain schedule, without changing the
graph, row coverage, arithmetic or memory timing. This is not a mux-only
change: merger row addresses, Apply's ordered offsets and source writeback
currently require global order. Any candidate must preserve unique complete
row coverage, finite buffering, round barriers and physical traffic, and
replay the unchanged controls before broader testing. This experiment has
not implemented that schedule or proved that it can reach the 10% target.
Do not hide the remaining gap with a cycle multiplier or promote this arm.

## Owners And Reproduction

The first attempt is retained at `convergence-v1/`. The candidate was rejected
before numerical execution because the harness's physical-master assertion
still expected fifteen masters. Its runner was stopped, so its unchanged
`RUNNING_COMPLETE_CONVERGENCE_MATRIX` report is not completed evidence. The
separate [stopped-attempt index](apply_ports_stopped.json) pins that report,
source archive and error. The corrected harness derives the expected count
from one shared helper, and the control test constructs five actual topologies
to verify 9/7/11/15/16 registered masters. No timing or workload changes are
made by this harness correction. A fresh attempt must rerun the complete gates.

The enum/configuration is in `cpp/include/spine_sim/routed_regraph.hpp`;
validation and wiring stay in the existing routed admission/composition
owners. No numerical component is duplicated. The thin `apply_ports.py`
CLI reuses the convergence runner, safety policy and finite-port analysis.
Focused analysis rejection tests are `tests/test_regraph_apply_ports.py`.

From the repository root, choose unused output and service names:

```sh
systemd-run --user --wait --pipe --collect --unit=spine-r-apply-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=100min -p CPUAffinity=124 -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.apply_ports \
  --output /data/chuxiao/experiments/r_apply_ports_20261022/convergence-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --before /data/chuxiao/experiments/r_metadata_ports_20261022/convergence-v1/results.json \
  --freeze /data/chuxiao/experiments/r_apply_ports_20261022/before/freeze.json \
  --cpus 124
```

After completion, use the shared `r_bank_stream.software_compatibility` CLI
with this campaign's `results.json` and the preceding five-case baseline at
`/data/chuxiao/experiments/sharded_k4_bank_stream_profile_20261019/gates-v1/legacy_final`.
Use a new SST output, the same 6/5-GiB max/high and zero swap. Raw artifacts
stay under `/data/chuxiao/experiments/r_apply_ports_20261022/`, outside Git.
The runner enforces a live 24-GiB reserve and 8-GiB background allowance,
requiring at least 38 GiB plus bounded peers before its one-worker build.
