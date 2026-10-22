# Separate Physical Metadata-Port Experiment

## Scope And Hypothesis

Simulator only. The preceding [dual-reader result](ELASTIC_PIPELINE.md)
takes 1.787 / 2.209 times strong original A4 cycles. It does not meet the
declared 0.9--1.1 retention interval. This experiment asks whether separating
directory traffic from the even-PMA master reduces the remaining input waits.
It is an explicit architecture change, not a timing-model correction.

The new default-off `kTriplePrefetchElasticExperimental` input path gives
each frontend three distinct streaming AXI masters: even PMA, odd PMA and
directory/extent. The two-pair source topology and shared Apply remain.
The complete path has **15 physical masters**, versus 11 for the preceding
dual path and 13 for A4. Each arm retains its preceding memory-bank mapping;
this does not mean A4 and K4 use identical mappings. The latency controls
are common. This is not strict resource equivalence: adding four masters
adds finite issue/return capability and parent storage. A4 also has four
state replicas, while the candidate retains three.

No PMA slot, directory read, source-state access or publication is free.
The two 256-line PMA rings, 1024-row directory tile, sixteen parents per
master, sixteen-beat limit, capacity-three/latency-two local pipelines,
71-cycle issue-to-use minimum, registered arbitration and backend credits
are unchanged. Default input selection and all old controls stay unchanged.
No FPGA/HLS build, board test, paper edit or figure replacement is included.

## Frozen Reference And Matrix

The pre-edit checkpoint is `d83f51e296b0f4928ca9bf2125c7a8926c12c6d2`.
`/data/chuxiao/experiments/r_metadata_ports_20261022/before/freeze.json`
records its committed-source archive, empty pre-edit dirty diff, compiler
executable and preceding complete-convergence report. The archive reads fixed
HEAD, not the later working tree; its final hash was checked after completion.
The fresh runner additionally archives/pins the edited source, compiler,
configuration, inputs and references before building, then pins new binaries.

The matrix is twelve executions: `a4_io16`, `prefetch_dual_elastic` and
`prefetch_triple_elastic`, each at mock latency 64/128 and both registration
orders. It uses the unchanged Amazon real-ID slice: 258,046 vertices,
1,450,899 weighted edges, four destination shards, old converged SSSP state
and three source-0 weight decreases. Every execution must complete all 46
synchronous rounds at 150 MHz. The boundary starts with post-update PMA,
old state and seed resident and ends after convergence/publication. G, host
preparation, DMA and orchestration are excluded from both sides.

## Gates

1. Fresh Release core: all 36 CTest targets and explicit topology controls.
   Integrated compact-input coverage grows from 24 to 32 executions, adding
   triple input to the same empty/throttled/window/partition/restart checks.
2. Fresh finite-input harness: preserve all 96 preceding synthetic executions
   and four publisher configurations, plus 16 triple-master executions. Test
   both latencies, both registration orders, fast/throttled sinks, dummy input,
   tile/ring/window crossings, per-port credits and byte/request closure.
3. Exactly replay all eight old A4/dual rows: cycles, traffic, round active
   counts and final padded output hashes. New orderings must also agree.
4. Match the independent oracle, every round's active count and all final
   state replicas. This is not complete intermediate-state capture.
5. Match old physical read/write totals; conserve every request, beat and lane.
6. Require triple/A4 in 0.9--1.1 at **both** latencies. Report all failures.
7. Fresh SST software plugin and exact five-case default replay. This checks
   compatibility, not triple-path FPGA timing or per-stage calibration.
8. Recheck all source/input/compiler/build/reference/progress pins at the end.

These gates do not establish original-publication reproduction or complete
G+R admission. A new Spine comparison remains separate and is not implied by
a faster reader, a correct run or a single passing latency.

## Result

All twelve complete executions pass correctness/conservation; all eight
pre-edit controls replay exactly, including cycles, traffic, active trajectory
and final padded state. Forward/reverse registration agrees exactly. The
fresh Release core passes all 36 CTest targets, explicit topology controls,
112 finite-input executions and four publisher-storage probes. Source,
compiler, input, binary and reference pins remain unchanged. The fresh SST
software plugin also passes all five default replay cases, with exact cycles,
counters and result hashes. This checks compatibility, not candidate timing.
The [compact evidence index](metadata_ports.json) retains the report, plugin,
input, source, log and passive-progress identities. All 2,390 core pins,
40 progress pins and 2,751 SST/reference pins were reverified.

| Complete 46-round R | Memory latency 64 | Memory latency 128 |
| --- | ---: | ---: |
| Strong original A4 | 10,904,254 cycles | 15,840,606 cycles |
| Preceding dual/elastic candidate | 19,487,578 cycles | 34,988,382 cycles |
| Separate metadata-master candidate | 17,419,740 cycles | 30,685,450 cycles |
| New / A4 | **1.5975** | **1.9371** |
| Cycle reduction from dual | 10.61% | 12.30% |
| Declared 0.9--1.1 retention interval | **Fail** | **Fail** |

The improvement is real within this fixed prediction experiment, but neither
latency meets the performance-retention gate. Adding ports alone has not
closed the gap. The candidate remains default-off and is not an admitted
replacement baseline. G, host timing, published-paper reproduction and a
new Spine comparison remain outside this result.

Both PMA candidates read 2,021,232,640 bytes and write 144,703,672 bytes;
A4 reads 802,534,400 bytes and writes 192,937,984 bytes. Those totals cover
all 46 rounds. The candidate has three state copies versus A4's four.
No traffic reduction or free metadata lookup explains the new speedup.

## What Remains Slow

The passive progress CSVs identify completion offsets and overlapping waits;
they do not isolate exclusive stage times or establish causality by themselves.
The following sums are offsets from each round's start, not additive costs:

| Completion endpoint, new candidate | Latency 64 | Latency 128 |
| --- | ---: | ---: |
| Last adapter | 10,906,048 | 18,142,308 |
| Last frontend compute | 17,392,922 | 30,637,794 |
| Apply done | 17,416,382 | 30,679,148 |
| Writeback done | 17,419,694 | 30,682,460 |
| Round end | 17,419,740 | 30,685,450 |
| Tail after last frontend | 26,818 | 47,656 |

At both latencies, the total improvement from dual is exactly the earlier
completion of the last adapter (2,067,838 / 4,302,932 cycles). Later endpoint
offsets shift by that same amount. This is consistent with relieving input
contention; it does not imply that the downstream work is free. The final
tail is only about 0.15%, so optimizing final drain alone cannot close the gap.

The fixed `partition_id % 4` assignment gives the four workers approximately
58.44%, 25.56%, 11.79% and 4.21% of compacted packets. Worker 0 is the last
adapter, yet worker 3 is the last compute frontend. Consecutive compute
completions remain separated by 35,328 / 68,096 cycles per round. The mux
consumes complete destination partitions in order. A4 instead gives all four
Little paths work within each destination partition; equal frontend counts
therefore do not imply equal scheduling.

The passive backend-wait tables are identical between dual and triple at
each latency. Apply reaches both 16-entry read/write windows. At latency 128,
the merger records 6,471,326 output-stall observations, and Apply records
11,753,644 read-window and 11,758,658 write-window waits. These observations
overlap other activity and each other; they are not a sum of lost cycles.

The next targeted controls should distinguish finite Apply read/write
concurrency from fixed-shard imbalance and ordered draining. Any extra
window, port, task split, partial-result storage or merge must be explicit,
charged and correctness-tested. Simply round-robin selecting existing Gather
outputs is invalid: the current Apply contract requires ordered global rows.
Likewise, reducing memory latency, omitting empty-directory scans or adding
an unmaintained index is not an acceptable way to reach the gate. No such
new control has been executed or claimed here.

## Owners And Reproduction

The implementation stays in `cpp/src/detail/prefetch_compact/` and the
existing routed input/composition/admission owners. A thin `metadata_ports.py`
entry point reuses the convergence runner and finite-port analysis; it does
not duplicate execution, preparation or safety logic in a top-level script.
Focused Python tests live in `tests/test_regraph_metadata_ports.py`.

Choose unused output/unit names from the repository root:

```sh
systemd-run --user --wait --pipe --collect --unit=spine-r-metadata-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=100min -p CPUAffinity=124 -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.metadata_ports \
  --output /data/chuxiao/experiments/r_metadata_ports_20261022/convergence-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --before /data/chuxiao/experiments/r_elastic_pipeline_20261022/convergence-v1/results.json \
  --freeze /data/chuxiao/experiments/r_metadata_ports_20261022/before/freeze.json \
  --cpus 124
```

Run the separate software compatibility gate only after the core report
finishes, keeping its numerical source owners unchanged:

```sh
systemd-run --user --wait --pipe --collect --unit=spine-r-metadata-sst-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=45min -p CPUAffinity=124 -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.software_compatibility \
  --output /data/chuxiao/experiments/r_metadata_ports_20261022/sst-NEW \
  --core-result /data/chuxiao/experiments/r_metadata_ports_20261022/convergence-NEW/results.json \
  --baseline /data/chuxiao/experiments/sharded_k4_bank_stream_profile_20261019/gates-v1/legacy_final
```

The service is one worker, hard limit 6 GiB, high limit 5 GiB, zero swap,
with a live 24-GiB available-memory reserve and 8-GiB background allowance.
Admission requires at least 38 GiB plus any reserved peers. Per-case time
and cycle limits remain finite. Only owned processes may be stopped.
The complete core service took 2,274.735 seconds and peaked at 850,006,016
bytes (810.6 MiB), with zero swap. Raw outputs stay outside Git under
`/data/chuxiao/experiments/r_metadata_ports_20261022/`. The separate SST
software build/replay took 508.318 seconds and peaked at 1,043,664,896 bytes
(995.3 MiB), with zero swap. Focused Python checks pass all 118 ReGraph
tests; the 15 repository-organization tests also pass. No running numerical
owner was edited during either campaign.
