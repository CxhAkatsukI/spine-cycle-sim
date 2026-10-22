# Compact-Input R To Complete Convergence

## Decision

Simulator-only experimental architecture. All twelve complete-convergence
executions pass correctness and conservation, with exact eight-row legacy
replay. The candidate improves the unchanged bank stream but remains
**2.591 / 2.197 times slower than strong A4**, failing the declared 10%
retention gate at both memory latencies. No production-baseline admission,
hardware match, publication reproduction or new Spine result is claimed.
No HLS, FPGA build or paper is changed.

## Fixed Scope

The input is the parent's frozen Amazon real-ID slice: 258,046 vertices,
1,450,899 positive weighted edges and four destination shards. Both systems
start with the same old-graph converged distances and three source-0 weight
decreases, with the updated graph and seed resident. The independent
synchronous oracle takes 46 rounds and checks full padded state and each
round's active count. This is weighted SSSP compute, not one PR iteration.
G updates, host preparation/orchestration and DMA are excluded on both sides.

The matrix is strong original `a4_io16`, unchanged `bank_stream` and
`prefetch_compact`, with mock read latencies 64/128 and both component
registration orders. The clock remains 150 MHz. The latter two arms retain
seven physical masters and three state copies; A4 has thirteen masters on
nine banks and four copies. Equal frontend count does not mean equal resources.
Mock-memory predictions do not reproduce a publication's measured throughput.

The candidate replaces only the input owner. Its explicit finite contract is
in the [reader/compactor guide](README.md). The existing source service,
Gather, shared Apply, writeback and round barriers remain in the path. The
packet stream terminates on TLAST with the physical packet count as an upper
bound, rather than pretending compaction reduced physical PMA reads. Legacy
physical-slot ingress remains the default. The experimental selection is not
exposed as an SST architecture and rejects unsupported zero-weight live edges.

## Gates

- Fresh Release C++ core: 36/36 tests pass in both campaigns, including
  new empty/throttled/multipart/window-crossing tests and TLAST restart bounds.
- Fresh SST software plugin builds; all five historical regression cases
  reproduce their frozen results. This is default-path compatibility, not
  candidate timing calibration. The full regression record remains under
  `compact-sst-v1/`.
- Eight old matrix rows exactly replay every cycle, traffic count, active count,
  state hash and file extent from the checked 32-row reference.
- Candidate forward/reverse registration agrees exactly. All expected
  state copies exist, agree with each other and match A4's logical state.
  Architectures intentionally have different replica filenames and counts.
- The harness checks live/dummy edges, all physical reads, Apply/source/status
  writes, closed parent/beat ledgers, drained AXI and the independent oracle.
- Retention requires candidate/A4 between 0.9 and 1.1 at both memory latencies.
  Correctness passing alone does not pass this performance gate.

## Completed Prediction

| Complete 46-round execution | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| Strong original A4 (`a4_io16`) | 10,904,254 | 15,840,606 |
| Unchanged bank stream | 32,178,380 | 57,588,504 |
| Experimental prefetch/compaction | 28,250,210 | 34,809,212 |
| Experimental / strong A4 | 2.59075 | 2.19747 |
| Cycle reduction versus bank stream | 12.2075% | 39.5553% |

All arms finish the same 46 rounds. Every padded state replica has 1,048,576
bytes and SHA-256
`ff001ca203b3b7e0b4ae60b630cee6755acd2f2401fb08e1069e081562dd2c00`.
The independent oracle checks full final state and the per-round active
trajectory, not a word-by-word capture of every intermediate round.

Across all rounds, both bank-stream arms read 2,021,232,640 bytes and write
144,703,672 bytes. A4 reads 802,534,400 bytes and writes 192,937,984 bytes.
Compaction removes dummy packet delivery, not physical PMA reads. Different
replica counts explain part of the write difference; they are not free copies.

The optional completion export gives the following **overlapping** sums of
offsets from each round's start for the experimental arm:

| Completion endpoint | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| Last adapter | 21,736,518 | 22,266,070 |
| Last frontend compute | 28,223,392 | 34,761,556 |
| Apply done | 28,246,852 | 34,802,910 |
| Writeback done | 28,250,164 | 34,806,222 |
| Status / round end | 28,250,210 | 34,809,212 |
| Tail after last frontend | 26,818 | 47,656 |

The final tail is only 0.095% / 0.137%; final drain alone cannot explain
the remaining gap. This does not make Apply free: backpressure overlaps
frontend execution. Worker 0 finishes the last adapter; worker 3 finishes
the last frontend despite having the fewest edges. Partition-ordered drain
and source/compute service need further isolation. Completion offsets are
not exclusive stage times or a causal stall attribution.

The portable [convergence evidence index](convergence.json) records source,
compiler, input, binary and raw-result identities, memory limits, retained
attempts, completion endpoints and explicit non-admission flags. The source
and artifact pins were verified unchanged at campaign completion.

## Retained Attempts

Raw root: `/data/chuxiao/experiments/r_bank_stream_comparison_20261022/`.

`compact-convergence-v1/` is intentionally retained as a partial interrupted
attempt, not a completed matrix. It passed all 36 core tests and completed
four rows. The first candidate gave 28,250,210 cycles versus old bank stream
32,178,380 and A4 10,904,254. Inspection found a summary-only error: it compared
whole output-file lists across architectures, so four A4 replica names could
never equal primary plus two K4 replicas. The serial run was stopped before
spending the remaining matrix time on that known invalid summary. No raw
observations were changed or promoted to a complete result.

The replacement summary validates every expected replica and compares its
full `(SHA-256, bytes)` logical state, not filenames across architectures.
Focused tests reject missing/extra/corrupt copies, wrong trajectories,
unclosed cycles, drift in legacy rows and incomplete matrices. They also
ensure a failed retention gate cannot become a hardware/baseline admission.
`compact-convergence-v2/` is a fresh source archive/build/run, not a rewritten v1.
It completes all twelve rows with no failures. The separate fresh SST build
replays all five default-path cases exactly; the experimental selection is
not exposed through SST, so that gate is compatibility, not candidate timing.

## Safe Reproduction

The parallel profile reserves the full 20-GiB cgroup plus 24-GiB live reserve
and 8-GiB background allowance, as well as finite peers' complete limits.
At most four subprocesses each have a 4-GiB address-space bound and 1800-second
timeout. The group has 18-GiB high, zero swap, group OOM kill and a 90-minute
wall-time bound. A watchdog kills only this owned group if live reserve falls.
The old single-worker 6/5-GiB profile is unchanged. CPU affinity, compiler,
source archive, binary, inputs and reference hashes are recorded in results.
The complete v2 service took 19 minutes 50.565 seconds, peaked at
1,227,538,432 bytes and used zero swap. Case-index CPU assignment can overlap
between workers; run duration is not an exclusive-core host benchmark.

From the repository root, choose unique unit/output names:

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-compact-convergence-NEW \
  -p MemoryMax=20G -p MemoryHigh=18G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=90min -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.prefetch_convergence \
  --output /data/chuxiao/experiments/r_bank_stream_comparison_20261022/compact-convergence-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --cpus 124 125 126 127

python3 -m unittest tests.test_regraph_compact_convergence \
  tests.test_regraph_bank_stream_runtime tests.test_regraph_bank_stream_comparison \
  tests.test_regraph_prefetch_compact
```

Each complete K4 run additionally exports read-only `rounds.csv` and
`invocations.csv` outside its state directory. Completion endpoints overlap;
their differences must not be mislabeled exclusive stage or causal stall time.
