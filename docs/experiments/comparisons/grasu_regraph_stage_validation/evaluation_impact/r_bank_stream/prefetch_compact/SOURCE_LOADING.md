# Independent Source-Cache Loading

## Scope And Decision

Simulator-only, default-off architecture experiment following the
[passive wait observations](OBSERVATIONS.md). The complete sixteen-row
convergence campaign and separate SST software regression pass correctness
and compatibility, but performance retention fails. No HLS,
FPGA build, board test, paper or figure package is changed.

The new complete R prediction is 27,465,634 / 34,058,814 cycles,
or **2.519 / 2.150 times strong A4**. This experiment does not change the
declared approximately 10% retention target to accommodate that mismatch.
The portable [evidence capsule](source_loading.json) records all sixteen rows,
source/input/build identities, checks and retained observations.

## Completed Result

| Arm | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| Strong A4, unchanged | 10,904,254 | 15,840,606 |
| Production bank-stream prediction, unchanged | 32,178,380 | 57,588,504 |
| Earlier finite prefetch/compaction, unchanged | 28,250,210 | 34,809,212 |
| Independent source-cache loading | 27,465,634 | 34,058,814 |
| New candidate / strong A4 | 2.519 | 2.150 |
| Cycle reduction from preceding compact input | 2.78% | 2.16% |

All four arms complete the same 46 rounds. Forward/reverse registration is
identical. All twelve pre-edit controls reproduce every numerical observation
and final output hash exactly. Candidate full final state in all three replicas
and every round's active count agree with the independent oracle/A4. This is
not a full intermediate-state capture. The candidate retains exactly
2,021,232,640 read bytes and 144,703,672 write bytes, like compact input.

The fresh Release core passes all **36 CTest targets**. A separate fresh SST
software build exactly reproduces all **five default-path cases**; the new
schedule is not exposed as an SST profile. The matrix completed in 25 minutes
45 seconds; its entire cgroup peaked at 1,227,698,176 bytes with zero swap.
SST peaked at 1,040,097,280 bytes with zero swap. These wall times describe
experiment execution, not modeled device or measured host latency.

### What The Diagnostic Establishes

At 64-cycle memory, both source services' output-stall counters fall from
9,267,298 / 10,999,106 to zero. Their line/parent counts and the backend
wait snapshots remain unchanged. Total time improves only 2.78%: removing
this backpressure alone does not recover the missing performance. Sampled
waits overlap; they cannot be added as an exclusive latency breakdown.

The summed last-adapter completion offset falls from 21,736,518 to 20,951,942
cycles, and last-compute from 28,223,392 to 27,438,816. The final tail after
frontends remains 26,818 cycles, below 0.1% of the total. These are completion
offsets from each round start, not additive stage costs.

The unchanged physical input remains a constraint: the separate stall-free
reader prediction needs 19,511,636 / 19,897,990 cycles for 46 scans, already
1.789 / 1.256 times A4's complete time. Shard 0 contains about 58.5% of live
edges but is assigned to one frontend, unlike A4's task subdivision. This
supports investigating input layout, physical padding and work distribution
next; it does not isolate their exclusive causal contributions or promise
that an unchanged layout can meet the 10% gate.

Any further layout/index or scheduling change must be a separately named,
finite architecture with its update/preparation costs paid. Do not selectively
reduce memory latency, use unregistered arbitration for contending clients,
weaken A4, or promote this candidate to a validated G+R/Spine comparison.

## Explicit Architecture

`RoutedSourceLoading::kEdgeCoupled` remains the default. The experimental
`kIndependentExperimental` selection lets Scatter drain at most one returned
64-byte source line per cycle during request, response, edge and emit phases,
even when edge consumption is blocked. This is a separate cache-write
schedule, not a reduced memory latency or a fitted speedup multiplier.

- Retain the two 4096-vertex ping-pong cache banks, 256 lines per bank and
  the existing replicated-lane cache organization. No third window is added.
- Request at most one window ahead of the currently consumed window.
  Alternating-bank ownership must prevent overwriting an in-use window.
- Only returned AXI data can enter the cache. Cache writes commit at the
  clock edge; edge mapping cannot consume a not-yet-committed line.
- Allow cache loading and edge access to proceed independently. This is an
  explicit concurrent cache-access assumption, not routed implementation
  evidence. Existing local-buffer write-byte accounting is retained.
- Retain source services, physical AXI masters, parent limits, FIFO capacities,
  memory timing, Gather, merger, Apply, state writeback and round barriers.
- Preserve terminal-marker draining, independent partition run-ahead and
  restart semantics. Never consume an end response as a normal cache line.

The `prefetch_source` harness arm combines this schedule with the preceding
finite prefetch/compacted-input candidate. All three old arms retain their
old configuration. The candidate is not selectable as an SST profile and
is not automatically promoted to the production baseline.

## Workload And Gates

Use the unchanged Amazon real-ID slice: 258,046 vertices, 1,450,899 weighted
edges and four destination shards. Start from the same old-graph converged
SSSP state, apply the same three source-0 weight decreases and complete all
46 synchronous propagation rounds. Updated graph and seed are resident;
G, host work and DMA are excluded equally. Clock is 150 MHz, with explicit
64/128-cycle mock memory and registered round-robin arbitration.

The matrix has four arms (`a4_io16`, `bank_stream`, `prefetch_compact`,
`prefetch_source`), both latencies and both registration orders: sixteen
executions. Strong A4 retains thirteen masters on nine banks and four state
copies; the candidate retains seven masters and three copies. This is not
strict resource equivalence or original-publication reproduction.

1. Fresh Release core and the complete CTest suite must pass. Connected
   Scatter tests exercise all five algorithm/format combinations, skipped
   source windows, small queues, throttling, dummy input and restart. The old
   depth-one request deadlock remains a checked legacy signature; the new
   schedule must make progress in that explicitly tested configuration.
2. All twelve pre-edit convergence rows must replay every numerical
   observation and full-state output exactly. A4 must not become slower.
3. Candidate registration orders must agree. Every full padded state replica
   and every round's active count must equal the independent oracle/A4.
   Requests, beats, physical packets and publication writes must close.
4. Physical read/write bytes must equal the preceding compact-input arm.
   This schedule change must not silently skip PMA reads or state work.
5. Candidate/A4 must lie between 0.9 and 1.1 at both latencies for retention.
   A complete correct matrix can still fail this performance gate.
6. A fresh SST software plugin must exactly replay all five historical
   default cases. That is default compatibility, not candidate timing
   calibration. Source/compiler/input/binary pins must remain unchanged.

Source loading alone is not promised to meet the target. The preceding
unchanged-reader floor, physical padding, unequal shard occupancy and
registered transport issue interval remain independently documented limits.

## Owners

| Owner | Responsibility |
| --- | --- |
| `cpp/include/spine_sim/routed_source_cache.hpp` | Explicit default and experimental schedule identities |
| `cpp/src/routed_regraph/scatter.cpp` | Bounded response consumption and edge processing |
| `cpp/src/routed_regraph/admission.cpp`, `composition.cpp` | Reject invalid selections and wire the declared schedule |
| `cpp/tests/evaluation_impact/control.hpp`, `k4_config.hpp` | Named candidate without changing old controls |
| `source_overlap.py`, `source_overlap_analysis.py` in the Python R study package | Thin CLI, complete-matrix admission and exact pre-edit replay |
| `prefetch_convergence.py` in that package | Shared fresh-build, containment, execution and pinning machinery |

## Frozen Evidence And Reproduction

Raw root: `/data/chuxiao/experiments/r_source_overlap_20261022/`.
`before/` retains the pre-edit twelve-row result and the committed source
archive. The completed archive SHA-256 is
`c3d2759dba1b4f5610f860a18a3d60a0da1f99e823448724dde107bd040fcbf6`;
the pre-edit `results.json` SHA-256 is
`5bc230ab0c5ce81608698fdded1191a09fa61377b1a27c3b5b306fa209ca2997`.
`convergence-v1/` and `sst-v1/` are separate immutable attempts.

Convergence has a 20/18-GiB hard/high limit, at most four workers, zero swap,
group OOM kill, a 90-minute timeout, 24-GiB live reserve and 8-GiB background
allowance. Admission reserves every bounded peer's full hard limit. SST
uses a separate 6/5-GiB group with the same reserve, zero swap and a 45-minute
timeout. Live watchdogs stop only owned groups if the reserve is breached.
No source changes are allowed while either campaign is live. CPU assignments
may overlap between workers; elapsed time is not a host-performance result.

Choose unused output/unit names and allowed CPUs from the repository root:

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-source-overlap-NEW \
  -p MemoryMax=20G -p MemoryHigh=18G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=90min -p CPUAffinity='124 125 126 127' \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.source_overlap \
  --output /data/chuxiao/experiments/r_source_overlap_20261022/convergence-NEW \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --before /data/chuxiao/experiments/r_source_overlap_20261022/before/results.json \
  --cpus 124 125 126 127

python3 -m unittest tests.test_regraph_source_overlap \
  tests.test_regraph_compact_convergence -q
```
