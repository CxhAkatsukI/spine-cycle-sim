# Finite Directory Lookahead

## Question And Declaration

This is a **simulator-only** follow-up to [split Apply](APPLY_PORTS.md).
No FPGA/HLS build, board run, paper edit or new hardware claim is authorized.
The preceding complete prediction takes 1.555 / 1.554 times A4. At latency
128 its observed last adapter endpoint takes 1.145 times complete A4 under
the existing output schedule. That endpoint includes downstream backpressure;
it is not a counterfactual lower bound for a different output schedule.

The new hypothesis is narrower: the single directory tile waits for its
selector and AXI parents to drain before reading the next tile. An explicit
second tile may overlap those reads with current PMA processing. This need
not remove fixed partition output serialization or reach the full target.

Before execution, declare all twelve complete-convergence observations:
`a4_io16`, `prefetch_triple_split_apply`, `prefetch_directory_lookahead`,
latencies 64/128, and both registration orders. Same Amazon real-ID slice,
258,046 vertices, 1,450,899 weighted edges, four destination shards, old
converged distances and three weight decreases. Run until final convergence
and publication, not one hop. The expected outcome is reduced input waiting;
the retention gate remains candidate/A4 in [0.9, 1.1] at **both** latencies.
The comparison ceiling is the independent same-input A4 model, not published
performance. No timing coefficient, bank service or mock latency is fitted.

## Architecture And Gates

`experimental_directory_tiles=2` is default-off and requires the dedicated
directory master of triple input. Four frontends each add 8 KiB of directory
values plus validity/control storage. Masters stay 16, versus A4's 13;
this is not a strict resource match. The source caches, 256-line PMA rings,
16-parent bounds, pipeline latency/capacity and split Apply are unchanged.

Each tile has explicit base ownership, issued lines, returned values and
three-cycle selector availability. A tile is reused only after current-row
selection and its AXI parents drain. The selector still skips at most eight
empty rows and joins at most one segment per cycle. Read-ahead issues through
the actual finite AXI master and pays every returned byte, including unused
trailing prefetch. At most one additional 8-KiB tile per frontend/round is
allowed versus the preceding stop point; physical writes must be unchanged.

Required gates: eight old complete trajectories/cycles/counters/state hashes
exact; new complete weighted state and active trajectory equal A4; both
registration orders identical; full request/beat/byte conservation; finite
tile ownership, partial tail, ring wrap, backpressure and invalid-configuration
tests; fresh complete CTest and default five-case SST compatibility. Default
SST replay is software regression evidence, not candidate timing calibration.

Source owners: `cpp/src/detail/prefetch_compact/directory.hpp` owns finite
tiles; existing reader request/join owners perform AXI and selector work.
The thin `r_bank_stream.directory_overlap` runner reuses complete convergence
and analysis, with an explicit bounded-prefetch traffic check. No duplicate
compute engine or numerical multiplier is introduced.

## Frozen Evidence And Reproduction

Pre-edit freeze:
`/data/chuxiao/experiments/r_directory_overlap_20261022/before/freeze.json`.
It pins commit `755788d`, 2,372 numerical/runner/configuration sources,
compiler, inputs, old binary/flags, reference outputs and the source archive.
The old dirty diff is empty. Raw evidence stays outside Git under that study
root. The complete CPU campaign is `convergence-v1/`; fresh default SST
software compatibility is checked separately in `sst-v1/`.

## Result And Decision

All twelve complete-convergence executions pass correctness, full padded
state and physical-traffic checks. Every arm has the same 46-round active
trajectory, all eight old controls replay exactly, and all six registration
order pairs agree. **Both performance-retention gates still fail.**

| Complete-convergence cycles | Latency 64 | Latency 128 |
| --- | ---: | ---: |
| Strong original A4, unchanged | 10,904,254 | 15,840,606 |
| One tile, separate Apply masters, unchanged | 16,950,908 | 24,619,522 |
| Two directory tiles | 16,128,290 | 24,591,738 |
| New candidate / A4 | 1.479082 | 1.552449 |
| Reduction from one tile | 4.8529% | 0.1129% |

The candidate reads 2,021,232,640 physical bytes and writes 144,703,672 bytes
at both latencies, identical to its preceding candidate. No extra prefetched
bytes occur on this declared input; the bound remains enforced for other
inputs. A4 reads 802,534,400 bytes and writes 192,937,984 bytes. Neither
master counts (16 versus 13) nor state copies (three versus four) are equal;
this is not strict resource equivalence. Added directory values total
32 KiB, plus validity, ready-cycle and ownership/control storage.

The fresh Release core passes all 36 CTest targets, including 48 compact-input
complete executions. Fourteen control arms, all 128 finite-input executions,
four publisher probes and two transport probes pass. Independent verification
checks all 2,396 source/compiler/input/binary/reference pins, all 40 progress
files and the pre-edit source archive/compiler/external references. The full
core campaign takes 38 minutes 27 seconds, with a service peak of 846,020,608
bytes and zero swap. It uses one CPU under the declared 6/5-GiB containment;
wall time is not simulated accelerator latency.

Fresh five-case SST compatibility passes: weighted SSSP cold/multipart warm,
CC, residual warm and residual update-only preserve every compared result
field, including cycles and counters. All 2,758 SST source/plugin pins verify.
The SST service takes 8 minutes 29 seconds, peaks at 1,045,278,720 bytes and
uses no swap. This is default-path regression, not candidate timing calibration.
All 125 focused ReGraph Python tests, 15 organization tests, document-layout,
generated-catalog and diff checks pass. Saved logs are in `quality-v1/`.
The compact [evidence index](directory_overlap.json) pins the complete reports;
raw source identities and outputs remain in those reports, not duplicated here.
G, host and a new Spine demo remain open.

## What The Observations Establish

Summed overlapping completion offsets across all 46 rounds are:

| New-candidate endpoint | Latency 64 | Latency 128 |
| --- | ---: | ---: |
| Last adapter | 10,083,430 | 18,114,524 |
| Last compute frontend | 16,112,144 | 24,559,170 |
| End after publication/drain | 16,128,290 | 24,591,738 |

Directory lookahead reduces the observed adapter endpoint by 822,618 cycles
at latency 64 but only 27,784 at latency 128. Complete cycles fall by the same
amounts. In both cases the interval between the last adapter and last compute
endpoint is unchanged, and the final tail is only 16,146 / 32,568 cycles.
These are overlapping endpoints, not additive stage costs or a complete
causal attribution. The narrow directory-overlap hypothesis helps latency 64
but does not explain most of the remaining gap.

In particular, the high-latency endpoint is still above complete A4, but its
backpressure dependence prevents treating it as an intrinsic input floor.
This corrects the stronger inference in the preceding Apply-port discussion;
no measured value or acceptance threshold changes. Fixed partition-order
draining and unequal shard work remain candidates for a controlled test.
Changing only mux arbitration is insufficient: merger row addresses, Apply
offset ordering and writeback currently depend on global partition order.
An alternative must explicitly preserve unique complete row coverage, finite
buffering, round barriers and request conservation. This study implements
neither that protocol nor a successful retention result. No timing coefficient
or source-derived A4 control was changed.

## Reproduction

From the repository root, use new output and service names:

```sh
systemd-run --user --wait --pipe --collect --unit=spine-r-directory-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=100min -p CPUAffinity=124 -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.directory_overlap \
  --output /data/chuxiao/experiments/r_directory_overlap_20261022/convergence-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --before /data/chuxiao/experiments/r_apply_ports_20261022/convergence-v2/results.json \
  --freeze /data/chuxiao/experiments/r_directory_overlap_20261022/before/freeze.json \
  --cpus 124
```

One CPU worker, 6/5-GiB cgroup max/high, zero swap, 24-GiB live reserve and
8-GiB background allowance remain unchanged. Sources cannot be edited during
the pinned run. G, host orchestration and a new Spine comparison remain
separate unfinished gates, irrespective of this candidate's result.
